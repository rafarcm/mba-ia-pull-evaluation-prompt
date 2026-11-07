"""
Script para fazer pull de prompts do LangSmith Prompt Hub.

Este script:
1. Conecta ao LangSmith usando credenciais do .env
2. Faz pull do prompt semente do desafio
3. Salva localmente em prompts/bug_to_user_story_v1.yml

DICAS DE IMPLEMENTAÇÃO:

- O pull é feito pelo cliente do LangSmith:

      from langsmith import Client
      client = Client()
      prompt = client.pull_prompt(
          "leonanluppi/bug_to_user_story_v1",
          dangerously_pull_public_prompt=True,
      )

- O parâmetro `dangerously_pull_public_prompt=True` é obrigatório sempre que o
  identificador tem dono explícito ("owner/nome"). O LangSmith bloqueia esse pull
  por padrão porque um prompt do Hub é um objeto LangChain serializado, que pode
  vir de terceiros. Aqui o prompt é o do desafio, então o risco é conhecido.

- O retorno é um ChatPromptTemplate. Para extrair o conteúdo das mensagens,
  use a serialização nativa do LangChain (`prompt.messages`, e o atributo
  `.prompt.template` de cada mensagem).

- Use `save_yaml` de utils.py para gravar o resultado no arquivo .yml.
"""

import sys
from datetime import date
from pathlib import Path
import yaml
from dotenv import load_dotenv
from langsmith import Client
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from utils import save_yaml, check_env_vars

load_dotenv()

# Prompt semente do desafio (dono/nome no LangSmith Hub)
SOURCE_PROMPT = "leonanluppi/bug_to_user_story_v1"

# Nome local do prompt: chave raiz no YAML e nome do arquivo
LOCAL_PROMPT_NAME = "bug_to_user_story_v1"

# Caminho resolvido a partir da raiz do projeto, para funcionar de qualquer cwd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "prompts" / f"{LOCAL_PROMPT_NAME}.yml"


def _str_representer(dumper: yaml.Dumper, value: str):
    """Grava textos com quebra de linha em bloco literal (|), legível no arquivo."""
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


# save_yaml (utils.py) usa yaml.dump com o Dumper padrão; registrar o representer
# aqui muda só a formatação do arquivo, sem alterar utils.py
yaml.add_representer(str, _str_representer)


def extract_messages(prompt: ChatPromptTemplate) -> dict:
    """
    Extrai o texto das mensagens system e user de um ChatPromptTemplate.

    Args:
        prompt: Template retornado por client.pull_prompt

    Returns:
        Dicionário com as chaves "system_prompt" e "user_prompt"

    Raises:
        ValueError: Se o template não tiver nenhuma mensagem system ou user
    """
    system_parts = []
    user_parts = []

    for message in prompt.messages:
        # MessagesPlaceholder e afins não têm `.prompt`: não há texto a extrair
        template = getattr(getattr(message, "prompt", None), "template", None)
        if isinstance(message, SystemMessagePromptTemplate) and template is not None:
            system_parts.append(template)
        elif isinstance(message, HumanMessagePromptTemplate) and template is not None:
            user_parts.append(template)
        else:
            # Aviso mantido: indica que parte do prompt do Hub não foi para o YAML
            print(f"⚠️  Mensagem ignorada no pull: {type(message).__name__}")

    if not system_parts and not user_parts:
        raise ValueError("O prompt não contém mensagens system ou user com texto")

    return {
        "system_prompt": "\n\n".join(system_parts),
        "user_prompt": "\n\n".join(user_parts),
    }


def build_prompt_data(prompt: ChatPromptTemplate) -> dict:
    """
    Monta a estrutura do YAML local a partir do prompt puxado do Hub.

    Mantém o mesmo formato do arquivo prompts/bug_to_user_story_v1.yml
    (chave raiz com description, system_prompt, user_prompt e metadados).
    """
    messages = extract_messages(prompt)
    hub_metadata = prompt.metadata or {}

    prompt_data = {
        "description": "Prompt para converter relatos de bugs em User Stories",
        "system_prompt": messages["system_prompt"],
        "user_prompt": messages["user_prompt"],
        # Metadados
        "version": "v1",
        "source": SOURCE_PROMPT,
        "pulled_at": date.today().isoformat(),
        "input_variables": sorted(prompt.input_variables),
        "tags": ["bug-analysis", "user-story", "product-management"],
    }

    # Commit do Hub, quando disponível, para saber exatamente qual versão foi puxada
    commit_hash = hub_metadata.get("lc_hub_commit_hash")
    if commit_hash:
        prompt_data["commit_hash"] = commit_hash

    return {LOCAL_PROMPT_NAME: prompt_data}


def pull_prompts_from_langsmith():
    """
    Faz pull do prompt semente do LangSmith Hub e o salva em YAML.

    Returns:
        True se sucesso, False caso contrário
    """
    client = Client()

    try:
        # O identificador tem dono explícito ("owner/nome"), então o LangSmith
        # exige confirmar que aceitamos carregar um objeto serializado de terceiros
        prompt = client.pull_prompt(SOURCE_PROMPT, dangerously_pull_public_prompt=True)
    except Exception as e:
        print(f"❌ Erro no pull de '{SOURCE_PROMPT}': {e}")
        print("   Verifique a LANGSMITH_API_KEY no .env e se o prompt é público no Hub.")
        return False

    try:
        data = build_prompt_data(prompt)
    except ValueError as e:
        print(f"❌ Não foi possível extrair o conteúdo do prompt: {e}")
        return False

    if not save_yaml(data, str(OUTPUT_PATH)):
        return False

    commit = data[LOCAL_PROMPT_NAME].get("commit_hash", "")[:8]
    print(
        f"✅ Pull de {SOURCE_PROMPT}{f' (commit {commit})' if commit else ''} "
        f"salvo em {OUTPUT_PATH.relative_to(PROJECT_ROOT)}"
    )
    return True


def main():
    """Função principal"""
    if not check_env_vars(["LANGSMITH_API_KEY"]):
        return 1

    return 0 if pull_prompts_from_langsmith() else 1


if __name__ == "__main__":
    sys.exit(main())
