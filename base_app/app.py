import streamlit as st
import json
import boto3
from utils.auth import Auth
from utils.llm import Llm

with st.sidebar:
    st.text(f"Welcome")
    

# Add title on the page
st.title("Generative AI Application")

