import os

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings

load_dotenv()


def get_chat_model() -> BaseChatModel:
    if os.getenv("CHAT_PROVIDER") == "ollama":
        model_name = os.getenv("CHAT_MODEL_NAME")
        return ChatOllama(
            model=model_name,
            temperature=0,
        )
    elif os.getenv("CHAT_PROVIDER") == "azure_openai":
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("CHAT_DEPLOYMENT_NAME")
        api_version = os.getenv("OPENAI_API_VERSION", "2024-12-01-preview")

        if not api_key or not endpoint or not deployment:
            raise RuntimeError(
                "Missing Azure OpenAI config. Set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and CHAT_DEPLOYMENT_NAME in backend/.env"
            )

        return AzureChatOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            temperature=0,
        )
    else:
        raise RuntimeError(
            "Invalid CHAT_PROVIDER. Set CHAT_PROVIDER to 'azure_openai' or 'ollama' in backend/.env"
        )

def get_embeddings_model() -> Embeddings:
    if os.getenv("EMBEDDING_PROVIDER") == "ollama":
        model_name = os.getenv("EMBEDDING_MODEL_NAME")
        return OllamaEmbeddings(
            model=model_name
        )
    elif os.getenv("EMBEDDING_PROVIDER") == "azure_openai":
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("EMBEDDING_DEPLOYMENT_NAME")
        api_version = os.getenv("OPENAI_API_VERSION", "2024-12-01-preview")

        if not api_key or not endpoint or not deployment:
            raise RuntimeError(
                "Missing Azure OpenAI embeddings config. Set AZURE_OPENAI_API_KEY, "
                "AZURE_OPENAI_ENDPOINT, and EMBEDDING_DEPLOYMENT_NAME in backend/.env"
            )

        return AzureOpenAIEmbeddings(
            api_key=api_key,
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
        )
    else:
        raise RuntimeError(
            "Invalid EMBEDDING_PROVIDER. Set EMBEDDING_PROVIDER to 'azure_openai' or 'ollama' in backend/.env"
        )


if __name__ == "__main__":
    llm = get_chat_model()
    print(llm.invoke("Hello, how are you?"))
    embeddings = get_embeddings_model()
    print(embeddings.embed_query("Hello, how are you?"))