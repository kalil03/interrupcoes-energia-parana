import holidays
import pandas as pd

from .config import ANOS, DATA_FINAL, PROCESSADOS
from .qualidade import cobertura_mensal
from .tratamento import salvar_parquet


def integrar_fontes(interrupcoes, ocorrencias, carga, clima):
    base = pd.DataFrame(index=pd.date_range("2022-01-01", DATA_FINAL, name="data"))
    for fonte in [interrupcoes, ocorrencias, carga, clima]:
        base = base.join(fonte, validate="one_to_one")
    feriados = holidays.country_holidays(
        "BR", subdiv="PR", years=list(ANOS), language="pt_BR"
    )
    calendario = pd.DataFrame({"data": base.index})
    calendario["feriado_nome"] = calendario.data.map(
        lambda data: feriados.get(data.date())
    )
    calendario["feriado_br_pr"] = calendario.feriado_nome.notna()
    calendario["dia_semana"] = calendario.data.dt.dayofweek
    calendario["fim_semana"] = calendario.dia_semana.ge(5)
    base = base.join(calendario.set_index("data"), validate="one_to_one")
    base["sem_registro_interrupcao"] = base.n_registros_interrupcao.isna()
    base["sem_registro_ocorrencia"] = base.n_registros_ocorrencia.isna()
    base["aneel_esquema_2026"] = base.index.year >= 2026
    base["ons_pos_mmgd_20230429"] = base.index >= pd.Timestamp("2023-04-29")
    return base.reset_index()


def exportar_base(base, processados=PROCESSADOS):
    salvar_parquet(base, "base_diaria_copel_pr", processados)
    cobertura_mensal(base).to_parquet(processados / "cobertura_mensal.parquet")
    return processados / "base_diaria_copel_pr.parquet"


def preparar_previsao_carga(base):
    dias = base.set_index("data").sort_index()
    proximo_dia = dias.index + pd.Timedelta(days=1)
    previsao = dias.filter(regex="^(ons_|clima_)").copy()
    previsao.index.name = "data_origem"
    previsao["data_alvo"] = proximo_dia
    previsao["carga_max_sul_d1_mwmed"] = dias.ons_sul_carga_max_horaria_mwmed.reindex(
        proximo_dia
    ).to_numpy()
    calendario = pd.Series(proximo_dia, index=dias.index)
    previsao["dia_semana_d1"] = calendario.dt.dayofweek
    for uf in ["PR", "SC", "RS"]:
        feriados = holidays.country_holidays(
            "BR", subdiv=uf, years=proximo_dia.year.unique().tolist()
        )
        previsao[f"feriado_{uf.lower()}_d1"] = [
            dia.date() in feriados for dia in proximo_dia
        ]
    return previsao.reset_index()


def preparar_conjuntos(base, processados=PROCESSADOS):
    eventos = pd.read_parquet(
        processados / "interrupcoes_copel.parquet",
        columns=[
            "data",
            "IdeConjuntoUnidadeConsumidora",
            "id_interrupcao",
            "DscTipoInterrupcao",
            "nao_programada",
            "uc_eventos",
        ],
    ).rename(columns={"IdeConjuntoUnidadeConsumidora": "conjunto"})
    if not eventos.DscTipoInterrupcao.isin(["Não Programada", "Programada"]).all():
        raise ValueError(
            "Revisar os tipos de interrupção antes de agregar por conjunto."
        )
    validos = eventos.conjunto.gt(0).fillna(False)
    sem_conjunto = eventos.loc[~validos].groupby("data").nao_programada.sum()
    eventos = eventos.loc[validos]
    chave = ["data", "conjunto"]
    painel = eventos.groupby(chave).size().rename("registros_total").to_frame()
    falhas = eventos.loc[eventos.nao_programada]
    if falhas.id_interrupcao.isna().any():
        raise ValueError("Interrupção não programada sem identificador.")
    grupos = falhas.groupby(chave)
    painel["registros_nao_programados"] = grupos.size().reindex(
        painel.index, fill_value=0
    )
    painel["interrupcoes_nao_programadas"] = grupos.id_interrupcao.nunique().reindex(
        painel.index, fill_value=0
    )
    painel["uc_eventos_nao_programados"] = grupos.uc_eventos.sum(min_count=1).reindex(
        painel.index, fill_value=0
    )
    por_dia = painel.groupby(level="data").registros_nao_programados.sum()
    apurado = por_dia.add(sem_conjunto, fill_value=0)
    esperado = base.set_index("data").n_nao_programadas.dropna()
    pd.testing.assert_series_equal(
        apurado.reindex(esperado.index, fill_value=0),
        esperado,
        check_dtype=False,
        check_names=False,
    )
    contexto = [
        "data",
        "aneel_esquema_2026",
        "ons_sul_carga_max_horaria_mwmed",
        "clima_max_precipitacao_mm",
        "clima_max_rajada_kmh",
        "feriado_br_pr",
    ]
    return (
        painel.reset_index().merge(base[contexto], on="data", validate="many_to_one"),
        sem_conjunto,
    )


def exportar_entregas(base, previsao, conjuntos, processados=PROCESSADOS):
    exportar_base(base, processados)
    salvar_parquet(previsao, "carga_sul_d1", processados)
    salvar_parquet(conjuntos, "interrupcoes_nao_programadas_conjunto_dia", processados)
    return pd.DataFrame(
        [
            ("carga_sul_d1.parquet", "Dia de origem", len(previsao)),
            (
                "interrupcoes_nao_programadas_conjunto_dia.parquet",
                "Conjunto e dia observado",
                len(conjuntos),
            ),
        ],
        columns=["Arquivo", "Uma linha por", "Linhas"],
    )
