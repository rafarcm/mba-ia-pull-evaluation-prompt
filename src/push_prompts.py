"""
Script para fazer push de prompts otimizados ao LangSmith Prompt Hub.

Este script:
1. Lê os prompts otimizados de prompts/bug_to_user_story_v2.yml
2. Valida os prompts
3. Faz push PÚBLICO para o LangSmith Hub
4. Adiciona metadados (tags, descrição, técnicas utilizadas)

Uso:
    python src/push_prompts.py            # valida e faz o push
    python src/push_prompts.py --dry-run  # só valida e mostra o que seria enviado

DICAS DE IMPLEMENTAÇÃO:

- O push é feito pelo cliente do LangSmith:

      from langsmith import Client
      from langchain_core.prompts import ChatPromptTemplate

      client = Client()
      prompt = ChatPromptTemplate.from_messages([
          ("system", system_prompt),
          ("user", user_prompt),
      ])
      url = client.push_prompt(
          f"{username}/bug_to_user_story_v2",
          object=prompt,
          is_public=True,
          description="...",
          tags=[...],
      )

- `username` vem de USERNAME_LANGSMITH_HUB no .env e precisa ser o seu handle
  do Hub. Se você ainda não tem um handle, veja as instruções no .env.example.

- A variável do template precisa ser {bug_report}, que é a chave de entrada
  usada no dataset de avaliação.

- Use `load_yaml` de utils.py para ler o arquivo .yml.
"""

import os
import re
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from langsmith import Client
from langsmith.utils import LangSmithConflictError
from langchain_core.prompts import ChatPromptTemplate
from utils import load_yaml, check_env_vars, validate_prompt_structure

load_dotenv()

# Nome do prompt: chave raiz no YAML, nome do arquivo e nome no Hub
PROMPT_NAME = "bug_to_user_story_v2"

# Variável de entrada usada pelo dataset de avaliação (inputs.bug_report)
REQUIRED_INPUT_VARIABLE = "bug_report"

# Caminho resolvido a partir da raiz do projeto, para funcionar de qualquer cwd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "prompts" / f"{PROMPT_NAME}.yml"


def validate_username(username: str) -> list:
    """
    Valida o handle do Hub. O identificador do prompt é "handle/nome", então o
    handle não pode conter "/" (ex: "meu-handle/projeto" é inválido).
    """
    if not username:
        return ["USERNAME_LANGSMITH_HUB está vazio"]
    if "/" in username or ":" in username or " " in username:
        return [
            f"USERNAME_LANGSMITH_HUB='{username}' não é um handle válido: use apenas o "
            "handle público (sem '/', ':' ou espaços), ex: 'meu-handle'. "
            "O nome do prompt é adicionado automaticamente pelo script."
        ]
    return []


def build_prompt_template(prompt_data: dict) -> ChatPromptTemplate:
    """Monta o ChatPromptTemplate (system + user) a partir dos dados do YAML."""
    return ChatPromptTemplate.from_messages([
        ("system", prompt_data["system_prompt"]),
        ("user", prompt_data["user_prompt"]),
    ])


def slugify(text: str) -> str:
    """Converte um texto em tag do Hub (ex: "Few-shot Learning" -> "few-shot-learning")."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_tags(prompt_data: dict) -> list:
    """Junta as tags do YAML, as técnicas aplicadas e a versão, sem repetições."""
    tags = list(prompt_data.get("tags", []))
    tags += [slugify(t) for t in prompt_data.get("techniques_applied", [])]
    tags.append(str(prompt_data.get("version", "")))
    return list(dict.fromkeys(tag for tag in tags if tag))


def build_readme(prompt_data: dict) -> str:
    """README exibido na página do prompt no Hub, com as técnicas utilizadas."""
    techniques = "\n".join(f"- {t}" for t in prompt_data.get("techniques_applied", []))
    return (
        f"# {PROMPT_NAME}\n\n"
        f"{prompt_data.get('description', '').strip()}\n\n"
        f"## Técnicas utilizadas\n\n{techniques}\n\n"
        f"## Entrada\n\n"
        f"- `{REQUIRED_INPUT_VARIABLE}`: texto do relato de bug\n\n"
        f"## Metadados\n\n"
        f"- Versão: {prompt_data.get('version', '')}\n"
        f"- Criado em: {prompt_data.get('created_at', '')}\n"
    )


def push_prompt_to_langsmith(prompt_name: str, prompt_data: dict) -> bool:
    """
    Faz push do prompt otimizado para o LangSmith Hub (PÚBLICO).

    Args:
        prompt_name: Nome do prompt
        prompt_data: Dados do prompt

    Returns:
        True se sucesso, False caso contrário
    """
    username = os.getenv("USERNAME_LANGSMITH_HUB", "").strip()
    prompt_identifier = f"{username}/{prompt_name}"
    techniques = prompt_data.get("techniques_applied", [])

    client = Client()
    try:
        url = client.push_prompt(
            prompt_identifier,
            object=build_prompt_template(prompt_data),
            is_public=True,
            description=prompt_data.get("description", "").strip(),
            readme=build_readme(prompt_data),
            tags=build_tags(prompt_data),
            commit_description=(
                f"{prompt_data.get('version', '')} - técnicas: {', '.join(techniques)}"
            )[:1000],
        )
    except LangSmithConflictError as e:
        # O LangSmith recusa um commit idêntico ao último. Os metadados (descrição,
        # readme, tags, visibilidade) já foram atualizados antes do commit, então
        # o prompt no Hub já está igual ao YAML local.
        if "nothing to commit" in str(e).lower():
            print(f"✅ {prompt_identifier} já está atualizado no Hub (sem mudanças no conteúdo)")
            return True
        print(f"❌ Conflito no push de '{prompt_identifier}': {e}")
        return False
    except Exception as e:
        print(f"❌ Erro no push de '{prompt_identifier}': {e}")
        print("   Verifique a LANGSMITH_API_KEY e o USERNAME_LANGSMITH_HUB (handle público do Hub) no .env.")
        return False

    print(f"✅ Push de {prompt_identifier} (público): {url}")
    return True


def validate_prompt(prompt_data: dict) -> tuple[bool, list]:
    """
    Valida estrutura básica de um prompt (versão simplificada).

    Args:
        prompt_data: Dados do prompt

    Returns:
        (is_valid, errors) - Tupla com status e lista de erros
    """
    # Campos obrigatórios, system_prompt vazio, TODOs e mínimo de 2 técnicas
    _, errors = validate_prompt_structure(prompt_data)

    user_prompt = prompt_data.get("user_prompt", "")
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        errors.append("user_prompt está vazio")
        return (False, errors)

    # O template precisa ser montável e usar exatamente a variável do dataset.
    # Chaves soltas no texto (ex: em exemplos few-shot) viram variáveis extras.
    try:
        variables = set(build_prompt_template(prompt_data).input_variables)
    except Exception as e:
        errors.append(f"Template inválido: {e}")
        return (False, errors)

    if REQUIRED_INPUT_VARIABLE not in variables:
        errors.append(f"Variável {{{REQUIRED_INPUT_VARIABLE}}} não encontrada no prompt")

    extra = variables - {REQUIRED_INPUT_VARIABLE}
    if extra:
        errors.append(
            f"Variáveis inesperadas no template: {', '.join(sorted(extra))} "
            "(escape chaves literais como {{ e }})"
        )

    # O relato deve entrar só no user prompt (problema de duplicação do v1)
    if f"{{{REQUIRED_INPUT_VARIABLE}}}" in prompt_data.get("system_prompt", ""):
        errors.append(
            f"{{{REQUIRED_INPUT_VARIABLE}}} está no system_prompt; use-o apenas no user_prompt"
        )

    return (len(errors) == 0, errors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push do prompt otimizado ao LangSmith Hub")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas valida o prompt e mostra o que seria enviado, sem fazer push",
    )
    return parser.parse_args()


def main():
    """Função principal"""
    args = parse_args()

    required_vars = [] if args.dry_run else ["LANGSMITH_API_KEY", "USERNAME_LANGSMITH_HUB"]
    if not check_env_vars(required_vars):
        return 1

    username = os.getenv("USERNAME_LANGSMITH_HUB", "").strip()
    username_errors = validate_username(username) if (username or not args.dry_run) else []
    if username_errors:
        for error in username_errors:
            print(f"❌ {error}")
        return 1

    data = load_yaml(str(PROMPT_PATH))
    if data is None:
        return 1

    prompt_data = data.get(PROMPT_NAME)
    if not isinstance(prompt_data, dict):
        print(f"❌ Chave '{PROMPT_NAME}' não encontrada em {PROMPT_PATH.name}")
        return 1

    is_valid, errors = validate_prompt(prompt_data)
    if not is_valid:
        print(f"❌ Prompt inválido ({PROMPT_PATH.relative_to(PROJECT_ROOT)}):")
        for error in errors:
            print(f"   - {error}")
        return 1

    if args.dry_run:
        print(
            f"🔎 Dry-run: prompt válido, nada foi enviado "
            f"(destino: {username or '<USERNAME_LANGSMITH_HUB>'}/{PROMPT_NAME})"
        )
        return 0

    return 0 if push_prompt_to_langsmith(PROMPT_NAME, prompt_data) else 1


if __name__ == "__main__":
    sys.exit(main())
