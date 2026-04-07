# will move the scraped JSON/markdown files to S3 for long-term storage and later retrieval by the RAG pipeline

import os
import boto3
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv

load_dotenv()

# for running locally without AWS credentials, we can mock the S3Manager to skip actual uploads and just print the intended actions.
class S3Manager:
    def __init__(self):
        self.enabled = all([
            os.getenv("AWS_ACCESS_KEY_ID"),
            os.getenv("AWS_SECRET_ACCESS_KEY"),
            os.getenv("S3_BUCKET_NAME")
        ])
        
        if self.enabled:
            # Only initialize Boto3 if keys actually exist
            self.s3 = boto3.client('s3') 
        else:
            print("⚠️ AWS Keys missing. S3 Uploads will be mocked.")

    def upload_file(self, local_path: str, s3_key: str):
        if not self.enabled:
            return f"local://{local_path}"
        # ... existing upload logic ...


# class S3Manager:
#     def __init__(self):
#         self.s3 = boto3.client(
#             's3',
#             aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
#             aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
#             region_name=os.getenv("AWS_REGION")
#         )
#         self.bucket_name = os.getenv("S3_BUCKET_NAME")

#     def upload_file(self, local_path: str, s3_key: str):
#         """Uploads a local file to your S3 bucket."""
#         try:
#             self.s3.upload_file(local_path, self.bucket_name, s3_key)
#             return f"s3://{self.bucket_name}/{s3_key}"
#         except Exception as e:
#             print(f"Error uploading to S3: {e}")
#             return None