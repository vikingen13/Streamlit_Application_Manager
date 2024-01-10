import streamlit as st
import json
import boto3
from utils.auth import Auth
from utils.llm import Llm

with st.sidebar:
    st.text(f"Welcome")
    

# Add title on the page
st.title("Generative AI Application")

# Ask user for input text
input_sent = st.text_input("Input Sentence", "Say Hello World! in Spanish, French and Japanese.")

# Create the large language model object
llm = Llm()

# When there is an input text to process
if input_sent:
    # Invoke the Bedrock foundation model
    response = llm.invoke(input_sent)

    # Transform response to json
    json_response = json.loads(response.get("body").read())

    # Format response and print it in the console
    pretty_json_output = json.dumps(json_response, indent=2)
    print("API response: ", pretty_json_output)

    # Write response on Streamlit web interface
    st.write("**Foundation model output** \n\n", json_response['completion'])
