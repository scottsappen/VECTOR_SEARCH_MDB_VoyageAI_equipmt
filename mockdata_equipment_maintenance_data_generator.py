#!/usr/bin/env python3
import json
from dotenv import load_dotenv
import os
import voyageai
from pymongo import MongoClient
import logging

# Load the .env file from the current directory
load_dotenv()

# Access variables
VOYAGEAI_API_KEY = os.getenv("VOYAGEAI_API_KEY")
VOYAGEAI_TEXT_EMBEDDING_MODEL = os.getenv("VOYAGEAI_TEXT_EMBEDDING_MODEL")
MONGODB_URI_STANDARD = os.getenv("MONGODB_URI_STANDARD")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EquipmentMaintenanceProcessor:
    def __init__(self):
        # VoyageAI configuration
        self.voyageai_api_key = VOYAGEAI_API_KEY
        self.text_embedding_model = VOYAGEAI_TEXT_EMBEDDING_MODEL
        
        # MongoDB configuration
        self.mongo_uri = MONGODB_URI_STANDARD
        self.db_name = MONGODB_DATABASE
        self.collection_name = MONGODB_COLLECTION
        
        # Initialize MongoDB client
        self.mongo_client = MongoClient(self.mongo_uri)
        self.db = self.mongo_client[self.db_name]
        self.collection = self.db[self.collection_name]
        
        logger.info(f"Initialized processor with MongoDB collection: {self.collection_name}")
    
    def get_voyageai_client(self):
        return voyageai.Client(api_key=self.voyageai_api_key)
    
    def create_summary(self, record):
        """Create a text summary of the maintenance record"""
        return f"""
        Maintenance log for equipment '{record['equipment_type']}' located in {record['location']}:

        Reported Issue: {record['reported_issue']}
        Diagnostic Findings: {record['diagnostic_findings']}
        Actions Taken: {record['actions_taken']}
        Post-Service Notes: {record['post_service_notes']}

        Service performed by {record['technician']['name']} ({record['technician']['certification']}).
        Severity Level: {record['severity_level']}, Duration: {record['service_duration_minutes']} minutes.
        """.strip()
    
    def get_embeddings(self, prompt):
        """Get embeddings from VoyageAI API"""
        try:
            client = self.get_voyageai_client()
            result = client.embed(prompt, model=self.text_embedding_model, input_type="document")
            return result.embeddings[0]
        except Exception as e:
            logger.error(f"Error retrieving embeddings: {e}")
            return []
    
    def process_maintenance_records(self, json_file_path):
        """Process maintenance records from JSON file"""
        try:
            # Load the JSON data
            with open(json_file_path, 'r') as f:
                records = json.load(f)
            
            logger.info(f"Loaded {len(records)} records from {json_file_path}")
            
            # Process each record
            for record in records:
                # Create the summary
                summary = self.create_summary(record)
                
                # Get embeddings
                embeddings = self.get_embeddings(summary)
                
                if not embeddings:
                    logger.warning(f"Skipping record {record['record_id']} due to empty embeddings")
                    continue
                
                # Create document for MongoDB
                mongo_doc = {
                    "record_id": record["record_id"],
                    "equipment_id": record["equipment_id"],
                    "equipment_type": record["equipment_type"],
                    "location": record["location"],
                    "service_date": record["service_date"],
                    "service_type": record["service_type"],
                    "reported_issue": record["reported_issue"],
                    "diagnostic_findings": record["diagnostic_findings"],
                    "actions_taken": record["actions_taken"],
                    "post_service_notes": record["post_service_notes"],
                    "severity_level": record["severity_level"],
                    "summary": summary,
                    "embeddings": embeddings
                }
                
                # Insert into MongoDB (upsert based on record_id)
                result = self.collection.update_one(
                    {"record_id": record["record_id"]},
                    {"$set": mongo_doc},
                    upsert=True
                )
                
                if result.upserted_id:
                    logger.info(f"Inserted record {record['record_id']}")
                else:
                    logger.info(f"Updated record {record['record_id']}")
            
            logger.info("Processing completed successfully")
            
        except Exception as e:
            logger.error(f"Error processing maintenance records: {e}")
            raise

def main():
    try:
        processor = EquipmentMaintenanceProcessor()
        
        # Path to the JSON file
        json_file_path = "mockdata_equipment-maintenance-logs.json"
        
        # Process the records
        processor.process_maintenance_records(json_file_path)
        
    except Exception as e:
        logger.error(f"Error in main function: {e}")

if __name__ == "__main__":
    main()