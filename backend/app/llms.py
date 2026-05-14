import os

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings


load_dotenv()


def get_chat_model() -> AzureChatOpenAI:
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


def get_embeddings_model() -> AzureOpenAIEmbeddings:
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


if __name__ == "__main__":
    llm = get_chat_model()
    print(llm.profile)