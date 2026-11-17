import json
import unicodedata

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .config import ANOS, BRUTOS, CNPJ, DATA_FINAL, PONTOS, PROCESSADOS


def salvar_parquet(df, name, processados=PROCESSADOS):
    processados.mkdir(exist_ok=True, parents=True)
    path = processados / f"{name}.parquet"
    if name.endswith("_revisao") and df.empty:
        path.unlink(missing_ok=True)
        return
    df.to_parquet(path, index=False)


def normalizar_cnpj(s):
    return (
        s.astype("string")
        .str.replace("\\.0$", "", regex=True)
        .str.replace("\\D", "", regex=True)
        .str.zfill(14)
    )


def validar_colunas(df, cols, name):
    missing = set(cols) - set(df.columns)
    if missing:
        raise ValueError(f"{name}: esquema inesperado: {missing}")


def ler_aneel(kind, qualidade, brutos=BRUTOS):
    frames = []
    for year in ANOS:
        paths = list(brutos.glob(f"{kind}_*{year}.parquet"))
        if len(paths) != 1:
            raise ValueError(f"Arquivo original ausente/ambíguo: {kind} {year}")
        f = pq.ParquetFile(paths[0])
        cnpj_col = next(
            (
                c
                for c in ["NumCPFCNPJ", "NumCNPJDistribuidora", "NumCnpjDistribuidora"]
                if c in f.schema_arrow.names
            ),
            None,
        )
        if cnpj_col is None:
            raise ValueError("CNPJ não identificado")
        kept = []
        for batch in f.iter_batches(batch_size=150000):
            codes = pc.utf8_lpad(
                pc.utf8_trim_whitespace(pc.cast(batch[cnpj_col], pa.string())),
                width=14,
                padding="0",
            )
            selected = batch.filter(pc.equal(codes, CNPJ))
            if selected.num_rows == 0:
                continue
            d = selected.to_pandas()
            d = d.loc[normalizar_cnpj(d[cnpj_col]).eq(CNPJ)].copy()
            if len(d):
                kept.append(d)
        if not kept:
            raise ValueError(f"Copel Distribuição não encontrada: {kind} {year}")
        d = pd.concat(kept, ignore_index=True)
        d["NumCPFCNPJ"] = normalizar_cnpj(d[cnpj_col])
        d["esquema_aneel"] = "2026" if year == 2026 else "ate2025"
        if year == 2026:
            if kind == "interrupcoes":
                mapping = {
                    "CodInterrupcao": "NumOrdemInterrupcao",
                    "CodConjUnidadeConsumidora": "IdeConjuntoUnidadeConsumidora",
                    "QtdConsumidoresAfetados": "NumUnidadeConsumidora",
                    "QtdConsumidoresAtivos": "NumConsumidorConjunto",
                    "AnoCompetencia": "NumAno",
                    "DscFatoGeradorTipo": "DscTipoInterrupcao",
                }
                for source, target in mapping.items():
                    d[target] = d[source]
                cols = [
                    "DscFatoGeradorOrigem",
                    "DscFatoGeradorTipo",
                    "DscFatoGeradorCausa",
                    "DscFatoGeradorDetalhe",
                ]
                d["DscFatoGeradorInterrupcao"] = (
                    d[cols[0]]
                    .fillna("")
                    .astype("string")
                    .str.cat(
                        [d[c].fillna("").astype("string") for c in cols[1:]], sep=" - "
                    )
                )
            else:
                mapping = {
                    "CodOcorrenciaEmergencial": "NumOcorrencia",
                    "DthIniOcorrencia": "DthInicioOcorrenciaAberta",
                    "DthFimOcorrencia": "DthFimOcorrenciaAberta",
                    "CodMunicipioIBGE": "CodIBGE",
                    "NumTempoPreparacao": "MdaPreparo",
                    "NumTempoDeslocamento": "MdaDeslocamento",
                    "NumTempoExecucao": "MdaExecucao",
                }
                for source, target in mapping.items():
                    d[target] = d[source]
        for c in [
            "NumAno",
            "IdeConjuntoUnidadeConsumidora",
            "NumUnidadeConsumidora",
            "NumConsumidorConjunto",
            "CodIBGE",
            "NumNivelTensao",
        ]:
            if c in d:
                d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
        for c in ["NumOrdemInterrupcao", "NumOcorrencia"]:
            if c in d:
                d[c] = d[c].astype("string")
        for c in [
            "DatGeracaoConjuntoDados",
            "DatInicioInterrupcao",
            "DatFimInterrupcao",
            "DthInicioOcorrenciaAberta",
            "DthFimOcorrenciaAberta",
        ]:
            if c in d:
                d[c] = pd.to_datetime(d[c], errors="coerce")
        for c in ["MdaPreparo", "MdaDeslocamento", "MdaExecucao"]:
            if c in d:
                d[c] = pd.to_numeric(
                    d[c].astype("string").str.replace(",", ".", regex=False),
                    errors="coerce",
                )
        d["arquivo_origem"] = paths[0].name
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    subset = [c for c in df if c not in ["DatGeracaoConjuntoDados", "arquivo_origem"]]
    dup = df.duplicated(subset=subset)
    df = df.loc[~dup].copy()
    qualidade[kind] = {
        "linhas_copel_originais": before,
        "duplicados_exatos": int(dup.sum()),
        "linhas_sem_duplicados": len(df),
    }
    return df


def preparar_interrupcoes(qualidade, brutos=BRUTOS, processados=PROCESSADOS):
    df = ler_aneel("interrupcoes", qualidade, brutos)
    validar_colunas(
        df,
        [
            "DatInicioInterrupcao",
            "DatFimInterrupcao",
            "NumOrdemInterrupcao",
            "IdeConjuntoUnidadeConsumidora",
            "DscFatoGeradorInterrupcao",
            "NumUnidadeConsumidora",
            "DscTipoInterrupcao",
        ],
        "interrupcoes",
    )
    for c in ["DatInicioInterrupcao", "DatFimInterrupcao"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["duracao_h"] = (
        df.DatFimInterrupcao - df.DatInicioInterrupcao
    ).dt.total_seconds() / 3600
    df["data"] = df.DatInicioInterrupcao.dt.normalize()
    df["inicio_invalido"] = df.data.isna() | ~df.data.between("2022-01-01", DATA_FINAL)
    df["duracao_invalida"] = df.duracao_h.isna() | df.duracao_h.lt(0)
    df["uc_invalida"] = df.NumUnidadeConsumidora.isna() | df.NumUnidadeConsumidora.lt(0)
    df["duracao_suspeita_7dias"] = df.duracao_h.gt(168)
    qualidade["interrupcoes"].update(
        {
            c: int(df[c].sum())
            for c in [
                "inicio_invalido",
                "duracao_invalida",
                "uc_invalida",
                "duracao_suspeita_7dias",
            ]
        }
    )
    salvar_parquet(
        df.loc[
            df.inicio_invalido
            | df.duracao_invalida
            | df.uc_invalida
            | df.duracao_suspeita_7dias
        ],
        "interrupcoes_revisao",
        processados,
    )
    df = df.loc[~df.inicio_invalido].copy()
    df["duracao_h_valida"] = df.duracao_h.mask(df.duracao_invalida)
    df["uc_eventos"] = df.NumUnidadeConsumidora.mask(df.uc_invalida)
    df["uc_horas"] = df.uc_eventos * df.duracao_h_valida
    df["nao_programada"] = (
        df.DscTipoInterrupcao.astype("string")
        .fillna("")
        .map(
            lambda x: "".join(
                (
                    c
                    for c in unicodedata.normalize("NFD", x.casefold().strip())
                    if unicodedata.category(c) != "Mn"
                )
            )
        )
        .eq("nao programada")
    )
    df["id_interrupcao"] = (
        df.NumAno.astype("string")
        + "|"
        + df.NumOrdemInterrupcao.astype("string").str.strip()
    )
    key = [
        "NumCPFCNPJ",
        "NumAno",
        "NumOrdemInterrupcao",
        "IdeConjuntoUnidadeConsumidora",
    ]
    conflicts = df.duplicated(key, keep=False)
    qualidade["interrupcoes"]["linhas_chave_repetida"] = int(conflicts.sum())
    salvar_parquet(df, "interrupcoes_copel", processados)
    g = df.groupby("data")
    daily = g.agg(
        n_registros_interrupcao=("id_interrupcao", "size"),
        n_ids_interrupcao=("id_interrupcao", "nunique"),
        n_nao_programadas=("nao_programada", "sum"),
        n_duracoes_validas=("duracao_h_valida", "count"),
        duracao_media_h=("duracao_h_valida", "mean"),
    )
    for src, dst in [("uc_eventos", "uc_eventos_soma"), ("uc_horas", "uc_horas_soma")]:
        daily[dst] = g[src].sum(min_count=1)
    salvar_parquet(
        df.groupby(["data", "DscFatoGeradorInterrupcao"], dropna=False)
        .size()
        .reset_index(name="n_registros"),
        "fatos_geradores_diarios",
        processados,
    )
    return daily


def preparar_ocorrencias(qualidade, brutos=BRUTOS, processados=PROCESSADOS):
    df = ler_aneel("ocorrencias", qualidade, brutos)
    validar_colunas(
        df,
        ["NumOcorrencia", "DthInicioOcorrenciaAberta", "DthFimOcorrenciaAberta"],
        "ocorrencias",
    )
    for c in ["DthInicioOcorrenciaAberta", "DthFimOcorrenciaAberta"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["data"] = df.DthInicioOcorrenciaAberta.dt.normalize()
    df["duracao_atendimento_h"] = (
        df.DthFimOcorrenciaAberta - df.DthInicioOcorrenciaAberta
    ).dt.total_seconds() / 3600
    df["data_invalida"] = df.data.isna() | ~df.data.between("2022-01-01", DATA_FINAL)
    df["duracao_invalida"] = (
        df.duracao_atendimento_h.isna() | df.duracao_atendimento_h.lt(0)
    )
    qualidade["ocorrencias"].update(
        {c: int(df[c].sum()) for c in ["data_invalida", "duracao_invalida"]}
    )
    salvar_parquet(
        df.loc[df.data_invalida | df.duracao_invalida],
        "ocorrencias_revisao",
        processados,
    )
    df["ibge_ausente_ou_suspeito"] = ~df.CodIBGE.astype("string").str.fullmatch(
        "41\\d{5}", na=False
    )
    for c in ["MdaPreparo", "MdaDeslocamento", "MdaExecucao"]:
        v = pd.to_numeric(df[c], errors="coerce")
        df[c + "_valido"] = v.mask(v.lt(0))
        qualidade["ocorrencias"][c + "_nulos_ou_negativos"] = int(
            (v.isna() | v.lt(0)).sum()
        )
    qualidade["ocorrencias"]["ibge_ausente_ou_suspeito"] = int(
        df.ibge_ausente_ou_suspeito.sum()
    )
    key = ["NumCPFCNPJ", "NumOcorrencia", "DthInicioOcorrenciaAberta"]
    repeated = df.duplicated(key, keep=False)
    qualidade["ocorrencias"]["linhas_chave_repetida"] = int(repeated.sum())
    df = df.loc[~df.data_invalida].copy()
    salvar_parquet(df, "ocorrencias_copel", processados)
    return df.groupby("data").agg(
        n_registros_ocorrencia=("NumOcorrencia", "size"),
        n_numeros_ocorrencia=("NumOcorrencia", "nunique"),
    )


def preparar_carga(qualidade, brutos=BRUTOS, processados=PROCESSADOS):
    frames = []
    for year in ANOS:
        p = brutos / f"ons_CURVA_CARGA_{year}.csv"
        d = pd.read_csv(p, sep=";")
        validar_colunas(
            d, ["id_subsistema", "din_instante", "val_cargaenergiahomwmed"], "ons"
        )
        frames.append(d.loc[d.id_subsistema.eq("S")].copy())
    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates()
    df["din_instante"] = pd.to_datetime(df.din_instante, errors="coerce")
    if df.duplicated(["id_subsistema", "din_instante"]).any():
        raise ValueError("ONS: timestamps conflitantes")
    df["carga_mwmed"] = pd.to_numeric(df.val_cargaenergiahomwmed, errors="coerce")
    hora_invalida = df.din_instante.isna() | df.din_instante.ne(
        df.din_instante.dt.floor("h")
    )
    bad = hora_invalida | df.carga_mwmed.isna() | df.carga_mwmed.lt(0)
    salvar_parquet(df.loc[bad], "ons_revisao", processados)
    qualidade["ons"] = {
        "originais_sul": before,
        "duplicados_exatos": before - len(df),
        "invalidos": int(bad.sum()),
        "zeros": int(df.carga_mwmed.eq(0).sum()),
    }
    df.loc[bad, "carga_mwmed"] = float("nan")
    df["data"] = df.din_instante.dt.normalize()
    salvar_parquet(df, "ons_sul_horario", processados)
    g = df.groupby("data")
    daily = g.agg(
        ons_sul_carga_media_mwmed=("carga_mwmed", "mean"),
        ons_sul_carga_max_horaria_mwmed=("carga_mwmed", "max"),
        ons_sul_horas_validas=("carga_mwmed", "count"),
    )
    daily["ons_dia_completo"] = daily.ons_sul_horas_validas.eq(24)
    daily.loc[
        ~daily.ons_dia_completo,
        ["ons_sul_carga_media_mwmed", "ons_sul_carga_max_horaria_mwmed"],
    ] = float("nan")
    return daily


def preparar_clima(qualidade, brutos=BRUTOS, processados=PROCESSADOS):
    frames = []
    for name in PONTOS:
        d = json.loads((brutos / f"clima_{name}_2026.json").read_text())
        assert d["timezone"] == "America/Sao_Paulo"
        df = pd.DataFrame(d["daily"]).rename(columns={"time": "data"})
        df["data"] = pd.to_datetime(df.data)
        df["ponto"] = name
        if df.duplicated(["data"]).any():
            raise ValueError("Clima duplicado")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    salvar_parquet(df, "clima_pontos", processados)
    cols = [c for c in df if c not in ["data", "ponto"]]
    g = df.groupby("data")
    daily = g[cols].mean().add_prefix("clima_media_")
    daily["clima_max_precipitacao_mm"] = g.precipitation_sum.max()
    daily["clima_max_rajada_kmh"] = g.wind_gusts_10m_max.max()
    daily["clima_pontos_completos"] = g[cols].count().min(axis=1)
    vals = [c for c in daily if c != "clima_pontos_completos"]
    daily.loc[daily.clima_pontos_completos.ne(5), vals] = float("nan")
    qualidade["clima"] = {
        "linhas_ponto_dia": len(df),
        "nulos": df[cols].isna().sum().to_dict(),
    }
    return daily
