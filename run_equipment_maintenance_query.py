from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField
from dotenv import load_dotenv
import voyageai
import os
import time

# Load the .env file from the current directory
load_dotenv()

# Access variables
VOYAGEAI_API_KEY = os.getenv("VOYAGEAI_API_KEY")
VOYAGEAI_TEXT_EMBEDDING_MODEL = os.getenv("VOYAGEAI_TEXT_EMBEDDING_MODEL")
CC_BOOTSTRAP_SERVER = os.getenv("CC_BOOTSTRAP_SERVER")
CC_CLUSTER_API_KEY = os.getenv("CC_CLUSTER_API_KEY")
CC_CLUSTER_API_SECRET = os.getenv("CC_CLUSTER_API_SECRET")
CC_SCHEMA_REGISTRY_URI = os.getenv("CC_SCHEMA_REGISTRY_URI")
CC_SCHEMA_REGISTRY_AUTH = os.getenv("CC_SCHEMA_REGISTRY_AUTH")
CC_TOPIC_USER_QUERY = os.getenv("CC_TOPIC_USER_QUERY")
                             
# Define the Avro schema - must match your Flink schema
user_query_schema_str = """
{
  "fields": [
    {
      "default": null,
      "name": "msg",
      "type": ["null", "string"]
    },
    {
      "default": null,
      "name": "vector",
      "type": [
        "null",
        {
          "items": ["null", "float"],
          "type": "array"
        }
      ]
    }
  ],
  "name": "user_query_embeddings_value",
  "namespace": "org.apache.flink.avro.generated.record",
  "type": "record"
}
"""

# Confluent Cloud configuration
conf = {
    'bootstrap.servers': CC_BOOTSTRAP_SERVER,
    'security.protocol': 'SASL_SSL',
    'sasl.mechanism': 'PLAIN',
    'sasl.username': CC_CLUSTER_API_KEY,
    'sasl.password': CC_CLUSTER_API_SECRET,
}

# Schema Registry configuration
schema_registry_conf = {
    'url': CC_SCHEMA_REGISTRY_URI,
    'basic.auth.user.info': CC_SCHEMA_REGISTRY_AUTH
}

# Initialize Schema Registry client
schema_registry_client = SchemaRegistryClient(schema_registry_conf)

# Initialize serializer
avro_serializer = AvroSerializer(
    schema_registry_client,
    user_query_schema_str
)

# Initialize the producer
producer = Producer(conf)

# Initialize VoyageAI client once (efficient)
voyage_client = voyageai.Client(api_key=VOYAGEAI_API_KEY)

def delivery_report(err, msg):
    """Callback function to report the result of the delivery attempt"""
    if err is not None:
        print(f"Delivery failed: {err}")
    else:
        print(f"Delivered message to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")

def get_embedding(query_text: str):
    """
    Get an embedding vector for the query_text using VoyageAI.

    NOTE: Avro schema uses 32-bit 'float'. VoyageAI returns Python floats (typically double precision).
    We cast to float to be explicit.
    """
    if not VOYAGEAI_API_KEY:
        raise RuntimeError("VOYAGEAI_API_KEY is not set")

    if not VOYAGEAI_TEXT_EMBEDDING_MODEL:
        raise RuntimeError("VOYAGEAI_TEXT_EMBEDDING_MODEL is not set")

    result = voyage_client.embed(
        query_text,
        model=VOYAGEAI_TEXT_EMBEDDING_MODEL,
        input_type="document"
    )
    # VoyageAI returns an object with .embeddings list
    emb = result.embeddings[0]

    # Ensure elements are castable to Avro 'float'
    emb_float32 = [float(x) for x in emb]
    return emb_float32

def send_user_query(query_text):
    """Send a user query to the user_query topic in Avro format, including the embedding vector."""
    # Compute embedding
    try:
        vector = get_embedding(query_text)
    except Exception as e:
        print(f"Embedding failed; sending msg without vector. Error: {e}")
        vector = None    

    # Build message per Avro schema
    message = {
        "msg": query_text,
        "vector": vector  # None or list[float]
    }
    print(f"Producing: msg length={len(query_text)}, vector_len={len(vector) if vector else 0}")

    # Serialize using Avro
    serialized_data = avro_serializer(
        message,
        SerializationContext(CC_TOPIC_USER_QUERY, MessageField.VALUE)
    )
    
    # Produce to Kafka
    producer.produce(
        CC_TOPIC_USER_QUERY,  # Topic name
        value=serialized_data,
        callback=delivery_report
    )
    producer.poll(0)  # Trigger any callbacks

def main():
    try:
        while True:
            # Get user input
            user_input = input("Enter your query (or 'exit' to quit): ").strip()
            
            # Check if user wants to exit
            if user_input.lower() == 'exit':
                break
                
            # Send the query to Confluent Cloud
            send_user_query(user_input)
            
            # Small delay between messages
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    finally:
        # Make sure all messages are sent before exiting
        print("Flushing remaining messages...")
        producer.flush()
        print("Done!")

if __name__ == "__main__":
    main()