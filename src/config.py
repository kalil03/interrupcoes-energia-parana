from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BRUTOS = RAIZ / "data/raw"
PROCESSADOS = RAIZ / "data/processed"
CNPJ = "04368898000106"
ANOS = range(2022, 2027)
DATA_FINAL = "2026-11-16"
PONTOS = {
    "curitiba": (-25.43, -49.27),
    "londrina": (-23.31, -51.16),
    "maringa": (-23.42, -51.94),
    "cascavel": (-24.96, -53.46),
    "ponta_grossa": (-25.10, -50.16),
}
