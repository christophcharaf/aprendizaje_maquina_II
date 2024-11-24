import os
from metaflow import FlowSpec, step, S3
import torch.nn as nn

# Configuración de las credenciales de acceso a AWS S3 (minio)
os.environ['AWS_ACCESS_KEY_ID'] = "minio"
os.environ['AWS_SECRET_ACCESS_KEY'] = "minio123"
os.environ['AWS_ENDPOINT_URL_S3'] = "http://localhost:9000"

# Clase de red neuronal previamente definida para cargar el modelo
class NeuralNetwork(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(NeuralNetwork, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_size, output_size)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.fc2(out)
        out = self.sigmoid(out)
        return out

class BatchProcessingModel(FlowSpec):

    @step
    def start(self):
        """
        Step para iniciar el flujo. Imprime un mensaje de inicio y avanza.
        """
        print("Starting Batch Prediction")
        self.next(self.load_data, self.load_model)

    @step
    def load_data(self):
        """
        Paso para cargar los datos de entrada de S3
        """
        import pandas as pd

        # Se utiliza el objeto S3 para acceder a los datos desde el bucket en S3.
        s3 = S3(s3root="s3://batch/")
        data_obj = s3.get("data/stroke_data.csv")
        
        self.X_batch = pd.read_csv(data_obj.path)
        self.next(self.batch_processing)


    @step
    def load_model(self):
        """
        Paso para cargar el modelo previamente entrenado.
        """
        import torch
        import torch.nn as nn
        import json


        # Se utiliza el objeto S3 para acceder al modelo desde el bucket en S3.
        with S3(s3root="s3://batch/") as s3:
            model_param = s3.get("artifact/rnn_model.json")

            # Cargar los parámetros del modelo desde el archivo JSON
            model_dict = json.loads(model_param.text)
            architecture = model_dict["architecture"]

            # Reconstruir el modelo
            model = NeuralNetwork(
                input_size=architecture["input_size"],
                hidden_size=architecture["hidden_size"],
                output_size=architecture["output_size"]
            )
            state_dict = {k: torch.tensor(v) for k, v in model_dict["state_dict"].items()}
            model.load_state_dict(state_dict)

        self.model = model
        self.next(self.batch_processing)


    @step
    def batch_processing(self, previous_tasks):
        """
        Paso para realizar el procesamiento por lotes y obtener predicciones con una red neuronal PyTorch.
        """
        import torch
        import numpy as np
        import hashlib
        import pandas as pd

        print("Obtaining predictions with the neural network model")

        # Se recorren las tareas previas para obtener los datos y el modelo.
        for task in previous_tasks:
            if hasattr(task, 'X_batch'):
                data = task.X_batch
            if hasattr(task, 'model'):
                model = task.model
        
        # Convertir los datos a tensores de PyTorch
        # pylint: disable=possibly-used-before-assignment
        data_tensor = torch.tensor(data.values, dtype=torch.float32)

        # Pasar los datos por el modelo para obtener las predicciones
        model.eval()  
        with torch.no_grad(): 
            outputs = model(data_tensor)
        # pylint: disable=possibly-used-before-assignment

        # Convertir las salidas del modelo a etiquetas binarias o índices según corresponda
        out = (outputs >= 0.5).int().numpy().flatten()  # Si es binario (0 o 1)

        # Diccionario de mapeo de etiquetas (ajústalo a tus clases)
        label_map = {0: "no_stroke", 1: "stroke"} 

        # Convertir las predicciones numéricas a etiquetas de texto
        labels = np.array([label_map[idx] for idx in out])

        # Generar un hash para cada fila de datos
        data['key'] = data.apply(lambda row: ' '.join(map(str, row)), axis=1)
        data['hashed'] = data['key'].apply(lambda x: hashlib.sha256(x.encode()).hexdigest())

        # Preparar los datos para Redis
        dict_redis = {}

        for index, row in data.iterrows():
            dict_redis[row["hashed"]] = labels[index]
       
        # Convertir el diccionario a un DataFrame y exportar el csv
        df_redis = pd.DataFrame(list(dict_redis.items()), columns=['Key', 'Value'])
        
        df_redis.to_csv("predictions.csv", index=False)

        self.redis_data = dict_redis

        self.next(self.ingest_redis)


    @step
    def ingest_redis(self):
        """
        Paso para ingestar los resultados en Redis.
        """
        import redis

        print("Ingesting Redis")
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)

        # Comenzamos un pipeline de Redis
        pipeline = r.pipeline()

        # Se pre-ingresan los datos en Redis.
        for key, value in self.redis_data.items():
            pipeline.set(key, value)

        # Ahora ingestamos todos de una y dejamos que Redis resuelva de la forma más eficiente
        pipeline.execute()

        self.next(self.end)

    @step
    def end(self):
        """
        Paso final del flujo. Imprime un mensaje de finalización.
        """
        print("Finished")


if __name__ == "__main__":
    BatchProcessingModel()
