# Carga do subsistema Sul e interrupções da Copel no Paraná

Ciência de Dados · UTFPR · Prof. Eduardo Pena
Daniel Suzuki Naves (RA 2363062), João Pedro Novais Zanusso (RA 2607743) e Kalil Nege (RA 2409020).

A Etapa 2 prepara duas bases diárias entre 01/01/2022 e 16/11/2026. A curva horária original do ONS reúne PR, SC e RS no subsistema Sul. Esse é o recorte para prever o maior valor horário da carga do dia seguinte. A investigação de interrupções usa outra escala: acompanha, no Paraná, os dias em que um mesmo conjunto elétrico da Copel registra interrupções não programadas.

## Executar

Com Python 3.10 e cerca de 4 GB livres, a partir da raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Abra o [notebook da Etapa 2](notebooks/01_preparacao_dados.ipynb), selecione o kernel da `.venv` e execute as células em ordem. A primeira execução baixa os originais para `data/raw/`. As seguintes reutilizam esses arquivos. Os módulos em `src/` fazem a coleta, o tratamento, a integração e as verificações.

Em seguida, abra o [notebook da Etapa 3](notebooks/02_investigacao_sql.ipynb). O foco é saber se as interrupções não programadas da Copel mudaram depois da privatização (agosto de 2023). O notebook consulta os Parquets de `data/processed/` com DuckDB e testa as hipóteses H1 a H4. O código fica em `src/`: `banco.py` (conexão e visões), `consultas.py` (as dez consultas SQL), `testes.py` (testes estatísticos) e `graficos.py`.

## Bases finais

Os Parquets são gerados localmente em `data/processed/` e ficam fora do Git.

| Arquivo | Cada linha representa | Medida principal |
|---|---|---|
| `carga_sul_d1.parquet` | Um dia de origem D | `carga_max_sul_d1_mwmed` é o máximo das 24 leituras horárias do Sul no dia civil D+1. |
| `interrupcoes_nao_programadas_conjunto_dia.parquet` | Um conjunto elétrico com algum registro no dia | `interrupcoes_nao_programadas` conta os IDs distintos de interrupções não programadas iniciadas no conjunto naquele dia. |

A mesma pasta contém os microdados filtrados, a integração estadual de conferência, a cobertura mensal e o manifesto com hashes dos originais. Uma nova coleta pode trazer revisões publicadas pelas fontes.

## Fontes e decisões

| Fonte | Uso na Etapa 2 |
|---|---|
| [ONS · Curva de carga](https://dados.ons.org.br/dataset/curva-carga) | Agregamos os CSVs horários do Sul por dia. Exigimos 24 horas distintas com carga válida para calcular a média e o máximo. Uma lacuna no dia previsto deixa o alvo ausente. |
| [ANEEL · Interrupções na distribuição](https://dadosabertos.aneel.gov.br/dataset/interrupcoes-de-energia-eletrica-nas-redes-de-distribuicao) | Filtramos a Copel Distribuição pelo CNPJ `04368898000106`. A recorrência conta dias com ao menos uma interrupção não programada por conjunto. |
| [ANEEL · Ocorrências emergenciais](https://dadosabertos.aneel.gov.br/dataset/ocorrencias-emergenciais-nas-redes-de-distribuicao) | Contamos os registros de atendimento pela data de abertura. Eles entram como série separada na integração estadual. |
| [Open-Meteo · ERA5](https://open-meteo.com/en/docs/historical-weather-api) | Calculamos médias simples para Curitiba, Londrina, Maringá, Cascavel e Ponta Grossa. Preservamos também os máximos espaciais de chuva e rajada. O agregado exige os cinco pontos completos. |
| Calendário · biblioteca `holidays` | Para carga, usamos os feriados nacionais e estaduais de PR, SC e RS na data prevista. Para os conjuntos da Copel, usamos o calendário do Paraná na data da interrupção. |

Na ANEEL, removemos duplicatas exatas e preservamos chaves repetidas com conteúdo diferente. Adaptamos os campos que mudaram em 2026 e mantemos o esquema de origem. A duração é atribuída ao dia de início. Durações negativas e quantidades inválidas ficam fora das respectivas medidas. Durações acima de sete dias são marcadas para revisão. A soma de unidades consumidoras afetadas pode incluir a mesma unidade em mais de um registro.

## Como interpretar as lacunas

- **Conjuntos elétricos.** Um dia com registros exclusivamente programados tem zero interrupções não programadas. Um dia sem registro para o conjunto fica fora da tabela. Códigos de conjunto ausentes ou não positivos entram somente na conferência do total da distribuidora.
- **Cobertura.** Na extração de 17/11/2026, a série da Copel chega a 30/09, a carga do ONS a 14/11 e o clima a 10/11. Junho de 2025 está sem registros de interrupções da Copel. Junho de 2026 tem cobertura parcial de ocorrências emergenciais. Antes de comparar períodos, consulte `data/processed/cobertura_mensal.parquet`.
- **Clima e previsão.** As cinco medições paranaenses dão contexto regional. Para usar a reanálise e a carga observada em uma previsão D+1, a modelagem deve respeitar a data em que cada informação ficou disponível.
