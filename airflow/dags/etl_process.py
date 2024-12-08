import datetime

from airflow.decorators import task
from airflow import DAG

MARKDOWN_TEXT = """
### ETL Process for Stroke Prediction Dataset

This DAG extracts information from Kaggle's  
[Stroke Prediction Dataset](https://www.kaggle.com/datasets/fedesoriano/stroke-prediction-dataset). 
It preprocesses the data by creating dummy variables and scaling numerical features.
    
After preprocessing, the data is saved back into a S3 bucket as two separate CSV files: one for training and one for 
testing. The split between the training and testing datasets is 70/30 and they are stratified.
"""


default_args = {
    "owner": "Gonzalo Gabriel Fernandez",
    "depends_on_past": False,
    "schedule_interval": None,
    "retries": 1,
    "retry_delay": datetime.timedelta(minutes=5),
    "dagrun_timeout": datetime.timedelta(minutes=15),
}



# Initialize the DAG
with DAG(
    "process_etl_stroke_prediction",
    description="ETL process for stroke prediction data, separating the dataset into training and testing sets.",
    default_args=default_args,
    schedule_interval=None,  # No automatic scheduling
    start_date=datetime.datetime(2024, 12, 1),
    tags=["ETL", "Stroke Prediction"],
    doc_md=MARKDOWN_TEXT,
    catchup=False,
) as dag:

    @task.virtualenv(
        task_id="fetch_save_dataset",
        requirements=["awswrangler", "pandas"],
        system_site_packages=True,
    )
    def fetch_save_dataset():
        """Save the dataset in s3"""
        import awswrangler as wr
        import pandas as pd
        import os

        dataset_zip_name = "stroke-prediction-dataset"
        dataset_url = f"http://192.168.1.185:12000/{dataset_zip_name}.zip" 
        dataset_csv_name = "healthcare-dataset-stroke-data"
        dataset_s3_path = f"s3://data/raw/{dataset_csv_name}.csv"

        os.system(f"curl --output {dataset_zip_name}.zip {dataset_url} && unzip {dataset_zip_name}.zip")
        df = pd.read_csv(f"{dataset_csv_name}.csv")
        df.set_index("id", inplace=True)
        wr.s3.to_csv(df=df, path=dataset_s3_path, index=False)

        return dataset_s3_path


    @task.virtualenv(
        task_id="make_dummies_variables",
        requirements=["awswrangler", "pandas", "mlflow"],
        system_site_packages=True
    )
    def make_dummies_variables():
        """Convert categorical variables into one-hot encoding."""
        # import json
        import datetime
        # import boto3
        # import botocore.exceptions
        import mlflow

        import awswrangler as wr
        import pandas as pd
        # import numpy as np
        # from airflow.models import Variable

        dataset_csv_name = "healthcare-dataset-stroke-data"
        dataset_raw_s3_path = f"s3://data/raw/{dataset_csv_name}.csv"
        # dataset_raw_s3_path = ti.xcom_pull(task_ids="fetch_save_dataset")
        dataset_dummies_path = f"s3://data/raw/{dataset_csv_name}_dummies.csv"

        df = wr.s3.read_csv(dataset_raw_s3_path)

        # Clean duplicates
        df.drop_duplicates(inplace=True, ignore_index=True)

        # Fill NaN
        df.dropna(inplace=True, ignore_index=True)
        df['bmi'].fillna(df['bmi'].median(), inplace=True)

        # Cathegoric variables transformation
        print("Applying One-Hot encoding to:")
        df_dummies = df.copy()
        for label, to_drop in [
            ("gender", "Other"),
            ("ever_married", "No"),
            ("work_type", "children"),
            ("Residence_type", "Rural"),
            ("smoking_status", "Unknown"),
        ]:
            unique_values = df_dummies[label].unique()
            print(label + ":", unique_values)
            prefix = "is" if len(unique_values) > 2 else label
            one_hot = pd.get_dummies(data=df_dummies[label], prefix=prefix).drop(
                prefix + "_" + to_drop if prefix else to_drop, axis=1
            )
            df_dummies.drop(label, axis=1, inplace=True)
            df_dummies = df_dummies.join(one_hot)

        wr.s3.to_csv(df=df_dummies, path=dataset_dummies_path, index=False)

        # Save information of the dataset
        # client = boto3.client('s3')

        # data_dict = {}
        # try:
        #     client.head_object(Bucket='data', Key='data_info/data.json')
        #     result = client.get_object(Bucket='data', Key='data_info/data.json')
        #     text = result["Body"].read().decode()
        #     data_dict = json.loads(text)
        # except botocore.exceptions.ClientError as e:
        #     if e.response['Error']['Code'] != "404":
        #         # Something else has gone wrong.
        #         raise e

        # target_col = Variable.get("stroke")
        # dataset_log = df.drop(columns=target_col)
        # dataset_with_dummies_log = df_dummies.drop(columns=target_col)

        # # Upload JSON String to an S3 Object
        # data_dict['columns'] = dataset_log.columns.to_list()
        # data_dict['columns_after_dummy'] = dataset_with_dummies_log.columns.to_list()
        # data_dict['target_col'] = target_col
        # data_dict['categorical_columns'] = categories_list
        # data_dict['columns_dtypes'] = {k: str(v) for k, v in dataset_log.dtypes.to_dict().items()}
        # data_dict['columns_dtypes_after_dummy'] = {k: str(v) for k, v in dataset_with_dummies_log.dtypes
                                                                                                #  .to_dict()
                                                                                                #  .items()}

    #     category_dummies_dict = {}
    #     for category in categories_list:
    #         category_dummies_dict[category] = np.sort(dataset_log[category].unique()).tolist()

    #     data_dict['categories_values_per_categorical'] = category_dummies_dict

    #     data_dict['date'] = datetime.datetime.today().strftime('%Y/%m/%d-%H:%M:%S"')
    #     data_string = json.dumps(data_dict, indent=2)

    #     client.put_object(
    #         Bucket='data',
    #         Key='data_info/data.json',
    #         Body=data_string
    #     )

        mlflow.set_tracking_uri('http://mlflow:5000')
        experiment = mlflow.set_experiment("ETL Stroke Prediction")

        mlflow.start_run(run_name='ETL_run_' + datetime.datetime.today().strftime('%Y/%m/%d-%H:%M:%S"'),
                         experiment_id=experiment.experiment_id,
                         tags={"experiment": "etl", "dataset": "Stroke Prediction"},
                         log_system_metrics=True)

        mlflow_dataset = mlflow.data.from_pandas(df,
                                                 source="https://www.kaggle.com/datasets/fedesoriano/stroke-prediction-dataset",
                                                 targets="stroke",
                                                 name="stroke_data_complete")
        mlflow_dataset_dummies = mlflow.data.from_pandas(df_dummies,
                                                         source="https://www.kaggle.com/datasets/fedesoriano/stroke-prediction-dataset",
                                                         targets="stroke",
                                                         name="stroke_data_complete_with_dummies")
        mlflow.log_input(mlflow_dataset, context="Dataset")
        mlflow.log_input(mlflow_dataset_dummies, context="Dataset")


    @task.virtualenv(
        task_id="split_dataset",
        requirements=["awswrangler", "scikit-learn", "imblearn"],
        system_site_packages=True,
    )
    def split_dataset():
        """Generate a dataset split into a training part and a test part."""
        import awswrangler as wr
        from sklearn.model_selection import train_test_split
        from imblearn.over_sampling import SMOTE

        def save_to_csv(df, path):
            wr.s3.to_csv(df=df, path=path, index=False)

        dataset_csv_name = "healthcare-dataset-stroke-data"
        dataset_dummies_path = f"s3://data/raw/{dataset_csv_name}_dummies.csv"

        dataset = wr.s3.read_csv(dataset_dummies_path)


        # test_size = Variable.get("test_size_heart")
        test_size = 0.2
        # target_col = Variable.get("stroke")
        target_col = "stroke"

        X = dataset.drop(columns=target_col)
        y = dataset[[target_col]]

        # fix classes imbalance
        smote = SMOTE(sampling_strategy="minority")
        X_smote , y_smote = smote.fit_resample(X, y)

        X_train, X_test, y_train, y_test = train_test_split(
            X_smote, y_smote, test_size=test_size, stratify=y_smote, random_state=42
        )

        # Clean duplicates
        # dataset.drop_duplicates(inplace=True, ignore_index=True)

        save_to_csv(X_train, f"s3://data/final/train/{dataset_csv_name}_X_train.csv")
        save_to_csv(X_test, f"s3://data/final/test/{dataset_csv_name}_X_test.csv")
        save_to_csv(y_train, f"s3://data/final/train/{dataset_csv_name}_y_train.csv")
        save_to_csv(y_test, f"s3://data/final/test/{dataset_csv_name}_y_test.csv")


    @task.virtualenv(
        task_id="normalize_numerical_features",
        requirements=["awswrangler", "scikit-learn", "mlflow"],
        system_site_packages=True,
    )
    def normalize_data():
        """
        Standardization of numerical columns
        """
        # import json
        # import mlflow
        # import boto3
        # import botocore.exceptions

        import awswrangler as wr
        import pandas as pd

        from sklearn.preprocessing import StandardScaler

        def save_to_csv(df, path):
            wr.s3.to_csv(df=df, path=path, index=False)

        dataset_csv_name = "healthcare-dataset-stroke-data"

        X_train = wr.s3.read_csv(f"s3://data/final/train/{dataset_csv_name}_X_train.csv")
        X_test = wr.s3.read_csv(f"s3://data/final/test/{dataset_csv_name}_X_test.csv")

        scaler=StandardScaler()
        X_train_arr = scaler.fit_transform(X_train)
        X_test_arr = scaler.fit_transform(X_test)

        X_train = pd.DataFrame(X_train_arr, columns=X_train.columns)
        X_test = pd.DataFrame(X_test_arr, columns=X_test.columns)

        save_to_csv(X_train, f"s3://data/final/train/{dataset_csv_name}_X_train.csv")
        save_to_csv(X_test, f"s3://data/final/test/{dataset_csv_name}_X_test.csv")

    #     # Save information of the dataset
    #     client = boto3.client("s3")

    #     try:
    #         client.head_object(Bucket="data", Key="data_info/data.json")
    #         result = client.get_object(Bucket="data", Key="data_info/data.json")
    #         text = result["Body"].read().decode()
    #         data_dict = json.loads(text)
    #     except botocore.exceptions.ClientError as e:
    #         # Something else has gone wrong.
    #         raise e

    #     # Upload JSON String to an S3 Object
    #     data_dict["standard_scaler_mean"] = sc_X.mean_.tolist()
    #     data_dict["standard_scaler_std"] = sc_X.scale_.tolist()
    #     data_string = json.dumps(data_dict, indent=2)

    #     client.put_object(Bucket="data", Key="data_info/data.json", Body=data_string)

    #     mlflow.set_tracking_uri("http://mlflow:5000")
    #     experiment = mlflow.set_experiment("Heart Disease")

    #     # Obtain the last experiment run_id to log the new information
    #     list_run = mlflow.search_runs([experiment.experiment_id], output_format="list")

    #     with mlflow.start_run(run_id=list_run[0].info.run_id):

    #         mlflow.log_param("Train observations", X_train.shape[0])
    #         mlflow.log_param("Test observations", X_test.shape[0])
    #         mlflow.log_param("Standard Scaler feature names", sc_X.feature_names_in_)
    #         mlflow.log_param("Standard Scaler mean values", sc_X.mean_)
    #         mlflow.log_param("Standard Scaler scale values", sc_X.scale_)

    fetch_save_dataset() >> make_dummies_variables() >> split_dataset() >> normalize_data()
