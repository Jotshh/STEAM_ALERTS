# Contribuindo

Obrigado por querer contribuir com o projeto.

## Ambiente local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export PYTHONPATH=src
```

No Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "src"
```

## Executar os testes

```bash
python -m pytest
```

Para consultar a Steam sem enviar alertas ou alterar o histórico:

```bash
python -m steam_alert.main --dry-run
```

## Preparando uma alteração

1. Crie uma branch a partir de `develop`.
2. Mantenha alterações pequenas e focadas.
3. Adicione ou atualise testes para comportamento novo ou corrigido.
4. Execute `python -m pytest` antes de abrir o Pull Request.
5. Não inclua URL real de webhook, arquivos `.env` ou dados privados.

## Relatar problemas

Use os templates disponíveis em `.github/ISSUE_TEMPLATE`. Inclua passos para reproduzir, resultado esperado, resultado obtido e detalhes do ambiente.
