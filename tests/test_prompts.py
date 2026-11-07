"""
Testes automatizados para validação de prompts.
"""
import re
import pytest
import yaml
import sys
from pathlib import Path

# Adicionar src ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils import validate_prompt_structure

PROMPT_NAME = "bug_to_user_story_v2"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / f"{PROMPT_NAME}.yml"


def load_prompts(file_path: str):
    """Carrega prompts do arquivo YAML."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def prompt_data() -> dict:
    """Dados do prompt otimizado (chave bug_to_user_story_v2 do YAML)."""
    assert PROMPT_PATH.exists(), f"Arquivo não encontrado: {PROMPT_PATH}"
    data = load_prompts(str(PROMPT_PATH))
    assert PROMPT_NAME in data, f"Chave '{PROMPT_NAME}' não encontrada no YAML"
    return data[PROMPT_NAME]


@pytest.fixture(scope="module")
def system_prompt(prompt_data) -> str:
    return prompt_data.get("system_prompt") or ""


class TestPrompts:
    def test_prompt_has_system_prompt(self, prompt_data):
        """Verifica se o campo 'system_prompt' existe e não está vazio."""
        assert "system_prompt" in prompt_data, "Campo 'system_prompt' não existe"
        assert isinstance(prompt_data["system_prompt"], str), "'system_prompt' deve ser texto"
        assert prompt_data["system_prompt"].strip(), "'system_prompt' está vazio"

    def test_prompt_has_role_definition(self, system_prompt):
        """Verifica se o prompt define uma persona (ex: "Você é um Product Manager")."""
        match = re.search(r"Você é (um|uma) ([^.\n]+)", system_prompt)
        assert match, "O prompt não define uma persona no formato 'Você é um/uma ...'"

        role = match.group(2).lower()
        known_roles = ["product manager", "product owner", "analista", "especialista"]
        assert any(r in role for r in known_roles), (
            f"A persona definida não é um papel de produto reconhecido: '{match.group(0)}'"
        )

    def test_prompt_mentions_format(self, system_prompt):
        """Verifica se o prompt exige formato Markdown ou User Story padrão."""
        text = system_prompt.lower()
        mentions_markdown = "markdown" in text
        mentions_user_story = "user story" in text and all(
            part in text for part in ("como um", "eu quero", "para que")
        )
        assert mentions_markdown or mentions_user_story, (
            "O prompt não exige formato Markdown nem o padrão de User Story "
            "('Como um ..., eu quero ..., para que ...')"
        )

        # Os critérios de aceitação devem seguir o padrão Gherkin
        for step in ("dado que", "quando", "então"):
            assert step in text, f"O prompt não menciona o passo Gherkin '{step}'"

    def test_prompt_has_few_shot_examples(self, system_prompt):
        """Verifica se o prompt contém exemplos de entrada/saída (técnica Few-shot)."""
        inputs = re.findall(r"^\s*Entrada:", system_prompt, flags=re.MULTILINE)
        outputs = re.findall(r"^\s*Saída:", system_prompt, flags=re.MULTILINE)

        assert len(inputs) >= 2, f"Few-shot exige ao menos 2 exemplos de entrada, há {len(inputs)}"
        assert len(inputs) == len(outputs), (
            f"Cada exemplo precisa de entrada e saída: {len(inputs)} entradas x {len(outputs)} saídas"
        )

        # Cada saída de exemplo deve demonstrar o formato de User Story
        example_outputs = re.split(r"^\s*Saída:", system_prompt, flags=re.MULTILINE)[1:]
        for i, example in enumerate(example_outputs, 1):
            assert "Como um" in example.strip()[:200], (
                f"A saída do exemplo {i} não começa com uma User Story ('Como um ...')"
            )

    def test_prompt_no_todos(self, prompt_data):
        """Garante que você não esqueceu nenhum `[TODO]` no texto."""
        for field in ("description", "system_prompt", "user_prompt"):
            value = str(prompt_data.get(field, ""))
            assert "[todo]" not in value.lower(), f"O campo '{field}' ainda contém [TODO]"

    def test_minimum_techniques(self, prompt_data):
        """Verifica (através dos metadados do yaml) se pelo menos 2 técnicas foram listadas."""
        techniques = prompt_data.get("techniques_applied")
        assert isinstance(techniques, list), "'techniques_applied' deve ser uma lista no YAML"
        assert len(techniques) >= 2, f"Mínimo de 2 técnicas, encontradas: {len(techniques)}"
        assert all(isinstance(t, str) and t.strip() for t in techniques), (
            "Há técnicas vazias em 'techniques_applied'"
        )
        assert any("few-shot" in t.lower() for t in techniques), (
            "Few-shot Learning é obrigatória e deve constar em 'techniques_applied'"
        )

    def test_prompt_uses_bug_report_only_in_user_prompt(self, prompt_data, system_prompt):
        """O relato entra uma única vez, no user prompt (corrige a duplicação do v1)."""
        assert "{bug_report}" in prompt_data.get("user_prompt", ""), (
            "O user_prompt precisa conter a variável {bug_report}"
        )
        assert "{bug_report}" not in system_prompt, (
            "{bug_report} não deve aparecer no system_prompt"
        )

    def test_prompt_structure_is_valid(self, prompt_data):
        """A mesma validação usada antes do push (campos obrigatórios, TODOs, técnicas)."""
        is_valid, errors = validate_prompt_structure(prompt_data)
        assert is_valid, f"Estrutura inválida: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
