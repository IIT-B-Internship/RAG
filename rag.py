from langchain_openai import ChatOpenAI
import requests
from langchain.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.docstore.document import Document
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Weaviate
import weaviate
from weaviate.embedded import EmbeddedOptions
import os
from langchain.prompts import ChatPromptTemplate
from langchain_community.llms import HuggingFaceHub
from langchain.llms import HuggingFaceHub
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.chat_models import ChatHuggingFace
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
from datasets import Dataset
from sentence_transformers import CrossEncoder
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
import streamlit as st
from sentence_transformers import SentenceTransformer
from ragas.metrics import faithfulness, answer_correctness, answer_similarity
from ragas import evaluate
from typing import Sequence
import pandas as pd
from Vector_database import VectorDatabase
from Rag_chain import RAGEval


class SentenceTransformerEmbeddings:
  def __init__(self, model_name: str):
      self.model = SentenceTransformer(model_name)

  def embed_documents(self, texts):
      return self.model.encode(texts, convert_to_tensor=True).tolist()

  def embed_query(self, text):
      return self.model.encode(text, convert_to_tensor=True).tolist()


class MistralParser():
  stopword = 'Answer:'
  parser = ''

  def __init__(self):
    self.parser = StrOutputParser()

  def invoke(self,query):
    ans = self.parser.invoke(query)
    return ans[ans.find(self.stopword)+len(self.stopword):].strip()


@st.cache_resource
def load_bi_encoder():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L12-v2",model_kwargs={"device": "cpu"})

@st.cache_resource
def load_embedding_model():
    return SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

@st.cache_resource
def load_cross_encoder():
    return CrossEncoder("cross-encoder/ms-marco-TinyBERT-L-2-v2", max_length=512, device="cpu")

@st.cache_resource
def load_chat_model():
    template = '''
    You are an assistant for question-answering tasks.
    Use the following pieces of retrieved context to answer the question accurately.
    If you don't know the answer, just say that you don't know.
    Question: {question}
    Context: {context}
    Answer:
    '''
    return HuggingFaceHub(
    repo_id="mistralai/Mistral-7B-Instruct-v0.1",
    model_kwargs={"temperature": 0.5, "max_length": 64,"max_new_tokens":512, "query_wrapper_prompt":template}
)

bi_encoder = load_bi_encoder()
embedding_model = load_embedding_model()
cross_encoder = load_cross_encoder()
chat_model = load_chat_model()

file_path = "software_data.txt"
url = st.secrets["WEAVIATE_URL"]
v_key = st.secrets["WEAVIATE_V_KEY"]
gpt_key = st.secrets["GPT_KEY"]
os.environ["HUGGINGFACEHUB_API_TOKEN"] = st.secrets["HUGGINGFACEHUB_API_TOKEN"]

mistral_parser = MistralParser()

re = RAGEval(file_path,url,v_key,gpt_key,embedding_model,cross_encoder) # file_path,url,vb_key,gpt_key):
re.model_prep(chat_model, mistral_parser) # model details

st.title('RAG Bot')
st.subheader('Converse with our Chatbot')
st.text("Some sample questions to ask:")
st.markdown("- What are adjustment points in the context of using a microscope, and why are they important?")
st.markdown("- What does alignment accuracy refer to, and how is it achieved in a microscopy context?")
st.markdown("- What are alignment marks, and how are they used in the alignment process?")
st.markdown("- What is the alignment process in lithography, and how does eLitho facilitate this procedure?")
st.markdown("- What can you do with the insertable layer in Smart FIB?")

if 'messages' not in st.session_state:
    st.session_state.messages = []
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What's up?"):
    st.markdown(prompt)
    st.session_state.messages.append({"role":"user", "content":prompt})

    response = re.query(prompt)

    with st.chat_message("assistant"):
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})

def reset_conversation():
  st.session_state.messages = []

st.button('Reset Chat', on_click=reset_conversation)
