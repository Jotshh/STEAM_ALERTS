# Steam Deal Alert

<!-- ![preview](./.github/preview.png) -->

![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat&logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat&logo=githubactions&logoColor=white)
![Steam](https://img.shields.io/badge/Steam-000000?style=flat&logo=steam&logoColor=white)
![Discord](https://img.shields.io/badge/Discord-5865F2?style=flat&logo=discord&logoColor=white)
![Pytest](https://img.shields.io/badge/Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)

Monitor automático de promoções da Steam. O projeto consulta os preços de jogos escolhidos na loja brasileira (BRL) e envia um alerta para um canal do Discord quando o desconto atinge o mínimo definido para cada jogo. Roda inteiro no GitHub Actions, sem servidor, sem banco de dados e sem custo.

---

## Execução

O monitor roda sozinho a cada 30 minutos pelo GitHub Actions. Para executar na hora: aba **Actions** > **Steam Monitor** > **Run workflow**.

https://github.com/Jotshh/steam-deal-alert/actions

---

## Tecnologias Utilizadas

* Python 3.12+
* [Requests](https://requests.readthedocs.io/) para as chamadas HTTP
* Steam Store API pública (`appdetails`)
* Discord Webhooks (embeds)
* GitHub Actions (agendamento e persistência do histórico)
* Pytest para os testes automatizados
* JSON para configuração e histórico

---

## Funcionalidades

- Monitoramento de vários jogos ao mesmo tempo, cada um com desconto mínimo próprio
- Adicionar, remover ou pausar jogos só editando `config/games.json`
- Alerta em embed do Discord com imagem, preço original, preço promocional, desconto, economia, link da Steam e horário
- Cor do embed muda conforme o tamanho do desconto
- Controle de duplicidade por App ID, desconto e estado da promoção
- Histórico em `data/alerts.json`, salvo pelo próprio workflow com commit automático só quando há mudança
- Tentativa de novo envio na próxima execução se o Discord falhar

---

## Regras de Alerta

| Situação | Alerta? |
|---|---|
| Promoção nova (desconto igual ou acima do mínimo) | Sim |
| Desconto mudou, para mais ou para menos, ainda acima do mínimo | Sim, a qualquer momento |
| Mesmo desconto, menos de 7 dias desde o último alerta | Não |
| Mesmo desconto, 7 dias ou mais desde o último alerta | Sim |
| Desconto caiu abaixo do mínimo ou a promoção acabou | Não, só atualiza o estado |
| Nova promoção depois de uma encerrada | Sim |

---

## Estrutura do Projeto

```
steam-deal-alert/
├── .github/
│   └── workflows/
│       └── steam-monitor.yml
├── src/
│   └── steam_alert/
│       ├── main.py
│       ├── steam_client.py
│       ├── deal_detector.py
│       ├── alert_manager.py
│       ├── discord_client.py
│       └── logger.py
├── config/
│   └── games.json
├── data/
│   └── alerts.json
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .env.example
└── LICENSE
```

---

## Como Usar

### 1. Criar o webhook do Discord

Configurações do Canal > Integrações > Webhooks > Novo Webhook > Copiar URL do Webhook. Trate a URL como senha.

### 2. Configurar o secret no GitHub

Settings > Secrets and variables > Actions > New repository secret:

- Name: `DISCORD_WEBHOOK_URL`
- Secret: a URL copiada

Em Settings > Actions > General, deixe **Read and write permissions** para o workflow poder salvar o histórico.

### 3. Escolher os jogos

Edite `config/games.json`. O App ID aparece na URL da loja (`store.steampowered.com/app/1245620/...`).

```json
{ "name": "Elden Ring", "appid": 1245620, "min_discount": 20, "enabled": true }
```

- `min_discount`: de 0 a 100
- `enabled: false` pausa o jogo; para remover, apague o item

### 4. Executar localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
export PYTHONPATH=src
python -m steam_alert.main --dry-run   # consulta e decide, sem enviar nem gravar
python -m steam_alert.main
```

### 5. Rodar os testes

```bash
python -m pytest
```

---

## Segurança e Qualidade

- A URL do webhook vem só da variável `DISCORD_WEBHOOK_URL` e nunca aparece em logs ou erros
- Validação do `games.json` e do `alerts.json`; arquivo corrompido interrompe a execução em vez de ser sobrescrito
- Timeout, retry com backoff e pausa entre requisições à Steam
- Tratamento de limite de requisições (429) do Discord
- `concurrency` no workflow evita execuções simultâneas
- Permissões mínimas: apenas `contents: write`
- Lógica de decisão separada das integrações externas, com testes usando mocks

---

## Limitações

- A API `appdetails` da Steam não é oficialmente documentada e pode mudar ou limitar requisições
- O cron do GitHub pode atrasar em horários de pico
- Em repositório público, o GitHub desativa workflows agendados após 60 dias sem atividade
- Em repositório privado, o plano gratuito tem 2.000 minutos/mês

---

## Licença

Este projeto está licenciado sob a MIT License.

---

## Suporte

Email: josiephelipel265@gmail.com

GitHub: [@Jotshh](https://github.com/Jotshh)