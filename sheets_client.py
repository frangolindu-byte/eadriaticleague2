import datetime
import logging
import time
from typing import Any, Callable, Dict, List

import gspread
from google.oauth2.service_account import Credentials

from config import Config


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
STATUS_FINALIZADO = "Finalizado"

HEADERS_BASE_DIARIA = ["Data Coleta", "Liga", "Jogador 1", "Placar", "Jogador 2", "Status"]
HEADERS_JOGOS_DIA = ["Liga", "Jogador 1", "Placar", "Jogador 2", "Status"]
HEADERS_RESUMO = ["Liga", "Total Jogos", "Finalizados", "Agendados", "Ultima Atualizacao"]
HEADERS_CLASSIFICACAO = ["#", "Jogador", "Pts", "J", "V", "E", "D", "GP", "GC", "SG"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Larguras em pixels
WIDTHS_BASE = [120, 260, 200, 80, 200, 110]
WIDTHS_JOGOS = [260, 200, 80, 200, 110]
WIDTHS_RESUMO = [260, 100, 100, 100, 160]

# Paleta profissional
C_HDR_BG = {"red": 0.13, "green": 0.18, "blue": 0.25}
C_HDR_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
C_ZEBRA = {"red": 0.96, "green": 0.97, "blue": 0.98}
C_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
C_FIN_BG = {"red": 0.85, "green": 0.95, "blue": 0.85}
C_FIN_FG = {"red": 0.13, "green": 0.55, "blue": 0.13}
C_AGE_BG = {"red": 1.0, "green": 0.96, "blue": 0.80}
C_AGE_FG = {"red": 0.72, "green": 0.53, "blue": 0.04}
C_BORDA = {"red": 0.82, "green": 0.84, "blue": 0.86}

logger = logging.getLogger("SheetsClient")

BORDA_SOLIDA = {"style": "SOLID", "width": 1, "color": C_BORDA}
BORDAS_TODAS = {
    "top": BORDA_SOLIDA, "bottom": BORDA_SOLIDA,
    "left": BORDA_SOLIDA, "right": BORDA_SOLIDA,
}


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
class SheetsClient:
    def __init__(self) -> None:
        creds = Credentials.from_service_account_file(
            Config.CREDENTIALS_PATH, scopes=SCOPES
        )
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(Config.SPREADSHEET_ID)
        logger.info("Planilha conectada: %s", self.spreadsheet.title)

    # --- retry --------------------------------------------------------------
    def _call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, Config.MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except gspread.exceptions.APIError as exc:
                is_rate_limit = "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc)
                if is_rate_limit and attempt < Config.MAX_RETRIES:
                    wait = Config.RETRY_DELAY * attempt
                    logger.warning("Rate limit - aguardando %ds", wait)
                    time.sleep(wait)
                    continue
                raise
            except Exception as exc:
                if attempt < Config.MAX_RETRIES:
                    logger.warning("Erro (tentativa %d): %s", attempt, exc)
                    time.sleep(Config.RETRY_DELAY)
                    continue
                raise

    # --- aba ----------------------------------------------------------------
    def _get_or_create_ws(self, title: str, headers: List[str]) -> gspread.Worksheet:
        try:
            ws = self.spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            logger.info("Criando aba '%s'", title)
            ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))

        # Sempre reescreve os headers na linha 1
        end_col = chr(ord("A") + len(headers) - 1)
        self._call(ws.update, f"A1:{end_col}1", [headers])
        return ws

    def _clear_below_header(self, ws: gspread.Worksheet, cols: int) -> None:
        all_values = self._call(ws.get_all_values)
        last_row = max(len(all_values) + 1, 500)
        end_col = chr(ord("A") + cols - 1)
        self._call(ws.batch_clear, [f"A2:{end_col}{last_row}"])

    def _data_rows_count(self, ws: gspread.Worksheet) -> int:
        return len(self._call(ws.get_all_values)) - 1

    # =====================================================================
    # LARGURAS DE COLUNA
    # =====================================================================
    def _set_column_widths(self, ws: gspread.Worksheet, widths: List[int]) -> None:
        sheet_id = ws.id
        requests = []
        for i, w in enumerate(widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize",
                }
            })
        if requests:
            self.spreadsheet.batch_update({"requests": requests})

    # =====================================================================
    # FORMATACAO
    # =====================================================================
    def _fmt_header(self, ws: gspread.Worksheet, cols: int) -> None:
        end = chr(ord("A") + cols - 1)
        self._call(ws.format, f"A1:{end}1", {
            "backgroundColor": C_HDR_BG,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
            "borders": BORDAS_TODAS,
            "textFormat": {
                "foregroundColor": C_HDR_FG,
                "bold": True,
                "fontSize": 11,
                "fontFamily": "Arial",
            },
        })

    def _fmt_borders(self, ws: gspread.Worksheet, cols: int, total: int) -> None:
        if total < 1:
            return
        end = chr(ord("A") + cols - 1)
        self._call(ws.format, f"A2:{end}{total + 1}", {
            "borders": BORDAS_TODAS,
            "wrapStrategy": "WRAP",
        })

    def _fmt_zebra(self, ws: gspread.Worksheet, cols: int, total: int) -> None:
        if total < 1:
            return
        end = chr(ord("A") + cols - 1)
        batch = []
        for i in range(2, total + 2):
            cor = C_ZEBRA if i % 2 == 0 else C_WHITE
            batch.append({
                "range": f"A{i}:{end}{i}",
                "format": {
                    "backgroundColor": cor,
                    "textFormat": {"fontSize": 10, "fontFamily": "Arial"},
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP",
                    "padding": {"top": 4, "bottom": 4, "left": 4, "right": 4},
                },
            })
        if batch:
            self._call(ws.batch_format, batch)

    def _fmt_status(self, ws: gspread.Worksheet, col: str, total: int) -> None:
        if total < 1:
            return
        vals = self._call(ws.get_all_values)
        batch = []
        for i, row in enumerate(vals[1:], start=2):
            if len(row) < 2:
                continue
            status = row[-1]
            if status == "Finalizado":
                bg, fg = C_FIN_BG, C_FIN_FG
            elif status == "Agendado":
                bg, fg = C_AGE_BG, C_AGE_FG
            else:
                continue
            batch.append({
                "range": f"{col}{i}",
                "format": {
                    "backgroundColor": bg,
                    "borders": BORDAS_TODAS,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {
                        "foregroundColor": fg, "bold": True,
                        "fontSize": 10, "fontFamily": "Arial",
                    },
                    "padding": {"left": 8, "right": 8},
                },
            })
        if batch:
            self._call(ws.batch_format, batch)

    def _fmt_center(self, ws: gspread.Worksheet, col: str, total: int) -> None:
        if total < 1:
            return
        self._call(ws.format, f"{col}2:{col}{total + 1}", {
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        })

    def _freeze(self, ws: gspread.Worksheet) -> None:
        self._call(ws.freeze, rows=1)

    # --- pipeline -----------------------------------------------------------
    def _format_all(
        self, ws: gspread.Worksheet, cols: int, n: int, tab: str, widths: List[int]
    ) -> None:
        self._fmt_header(ws, cols)
        self._freeze(ws)
        self._set_column_widths(ws, widths)
        if n > 0:
            self._fmt_borders(ws, cols, n)
            self._fmt_zebra(ws, cols, n)

        if tab == "jogos":
            self._fmt_status(ws, "E", n)
            self._fmt_center(ws, "C", n)
        elif tab == "base":
            self._fmt_status(ws, "F", n)
            self._fmt_center(ws, "D", n)
        elif tab == "resumo":
            for c in "BCDE":
                self._fmt_center(ws, c, n)

    # =====================================================================
    # BASE_DIARIA
    # =====================================================================
    def update_base_diaria(self, data: List[Dict[str, Any]]) -> int:
        ws = self._get_or_create_ws(Config.TAB_BASE_DIARIA, HEADERS_BASE_DIARIA)

        existing = self._call(ws.get_all_values)[1:]
        existing_keys = {tuple(r[:5]) for r in existing if len(r) >= 5}

        today = datetime.date.today().strftime("%d/%m/%Y")
        new_rows = []
        for item in data:
            key = (
                today,
                item.get("liga", ""),
                item.get("p1", ""),
                item.get("placar", ""),
                item.get("p2", ""),
            )
            if key not in existing_keys:
                new_rows.append([*key, item.get("status", STATUS_FINALIZADO)])

        if new_rows:
            self._call(ws.append_rows, new_rows)
            logger.info("%d novas partidas inseridas", len(new_rows))

        total = self._data_rows_count(ws)
        self._format_all(ws, len(HEADERS_BASE_DIARIA), total, "base", WIDTHS_BASE)
        return len(new_rows)

    # =====================================================================
    # JOGOS_DO_DIA
    # =====================================================================
    def update_jogos_do_dia(self, data: List[Dict[str, Any]]) -> None:
        ws = self._get_or_create_ws(Config.TAB_JOGOS_DIA, HEADERS_JOGOS_DIA)
        self._clear_below_header(ws, cols=5)

        rows = [
            [item.get("liga", ""), item.get("p1", ""), item.get("placar", ""),
             item.get("p2", ""), item.get("status", "")]
            for item in data
        ]

        if rows:
            self._call(ws.update, "A2", rows)

        self._format_all(ws, len(HEADERS_JOGOS_DIA), len(rows), "jogos", WIDTHS_JOGOS)
        logger.info("JOGOS_DO_DIA atualizado (%d partidas)", len(rows))

    # =====================================================================
    # RESUMO_POR_LIGA
    # =====================================================================
    def update_resumo(self, data: List[Dict[str, Any]]) -> None:
        ws = self._get_or_create_ws(Config.TAB_RESUMO, HEADERS_RESUMO)
        self._clear_below_header(ws, cols=5)

        now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        resumo: Dict[str, Dict[str, int]] = {}

        for item in data:
            liga = item.get("liga", "Desconhecida")
            if liga not in resumo:
                resumo[liga] = {"total": 0, "finalizados": 0, "agendados": 0}
            resumo[liga]["total"] += 1
            if item.get("status") == STATUS_FINALIZADO:
                resumo[liga]["finalizados"] += 1
            else:
                resumo[liga]["agendados"] += 1

        rows = [
            [liga, s["total"], s["finalizados"], s["agendados"], now]
            for liga, s in resumo.items()
        ]

        if rows:
            self._call(ws.update, "A2", rows)

        n = len(rows)
        self._format_all(ws, len(HEADERS_RESUMO), n, "resumo", WIDTHS_RESUMO)
        logger.info("Resumo atualizado (%d ligas)", n)

    # =====================================================================
    # CLASSIFICACAO POR LIGA
    # =====================================================================

    def _calc_classificacao(self, data: List[Dict[str, Any]]) -> Dict[str, List[List]]:
        """Calcula a classificacao de cada liga baseado nos jogos finalizados."""
        ligas: Dict[str, Dict[str, Dict[str, int]]] = {}

        for item in data:
            if item.get("status") != STATUS_FINALIZADO:
                continue

            liga = item.get("liga", "Desconhecida")
            p1 = item.get("p1", "")
            p2 = item.get("p2", "")
            placar = item.get("placar", "")

            if not p1 or not p2 or "-" not in placar:
                continue

            try:
                gols = placar.split("-")
                g1, g2 = int(gols[0]), int(gols[1])
            except (ValueError, IndexError):
                continue

            if liga not in ligas:
                ligas[liga] = {}

            for jogador in [p1, p2]:
                if jogador not in ligas[liga]:
                    ligas[liga][jogador] = {
                        "J": 0, "V": 0, "E": 0, "D": 0,
                        "GP": 0, "GC": 0, "Pts": 0,
                    }

            # Jogador 1
            ligas[liga][p1]["J"] += 1
            ligas[liga][p1]["GP"] += g1
            ligas[liga][p1]["GC"] += g2

            # Jogador 2
            ligas[liga][p2]["J"] += 1
            ligas[liga][p2]["GP"] += g2
            ligas[liga][p2]["GC"] += g1

            if g1 > g2:
                ligas[liga][p1]["V"] += 1
                ligas[liga][p1]["Pts"] += 3
                ligas[liga][p2]["D"] += 1
            elif g2 > g1:
                ligas[liga][p2]["V"] += 1
                ligas[liga][p2]["Pts"] += 3
                ligas[liga][p1]["D"] += 1
            else:
                ligas[liga][p1]["E"] += 1
                ligas[liga][p1]["Pts"] += 1
                ligas[liga][p2]["E"] += 1
                ligas[liga][p2]["Pts"] += 1

        # Monta tabelas ordenadas
        resultado: Dict[str, List[List]] = {}
        for liga, jogadores in ligas.items():
            tabela = []
            for nome, s in jogadores.items():
                sg = s["GP"] - s["GC"]
                tabela.append([nome, s["Pts"], s["J"], s["V"], s["E"], s["D"],
                               s["GP"], s["GC"], sg])
            # Ordena por Pts desc, SG desc, GP desc
            tabela.sort(key=lambda x: (x[1], x[8], x[6]), reverse=True)
            # Adiciona posicao
            for i, row in enumerate(tabela, 1):
                row.insert(0, i)
            resultado[liga] = tabela

        return resultado

    def _col_letter(self, col_index: int) -> str:
        """Converte indice 0-based para letra de coluna (A, B, ..., Z, AA, AB...)."""
        result = ""
        col_index += 1
        while col_index > 0:
            col_index, remainder = divmod(col_index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def update_classificacao(self, data: List[Dict[str, Any]]) -> None:
        """Escreve a classificacao de cada liga lado a lado com graficos."""
        classificacao = self._calc_classificacao(data)

        if not classificacao:
            logger.info("Nenhuma classificacao calculada")
            return

        ligas_ordenadas = sorted(classificacao.keys())
        COLS = len(HEADERS_CLASSIFICACAO)
        ESPACO = 1
        max_jogadores = max(len(v) for v in classificacao.values())
        total_rows = 2 + max_jogadores + 18  # dados + espaco + grafico
        total_cols = len(ligas_ordenadas) * (COLS + ESPACO)

        # Obtem ou cria aba (recria se colunas insuficientes)
        try:
            ws = self.spreadsheet.worksheet(Config.TAB_CLASSIFICACAO)
            if ws.col_count < total_cols:
                logger.info("Colunas insuficientes (%d < %d), recriando aba",
                            ws.col_count, total_cols)
                self.spreadsheet.del_worksheet(ws)
                ws = self.spreadsheet.add_worksheet(
                    title=Config.TAB_CLASSIFICACAO,
                    rows=total_rows + 10,
                    cols=total_cols + 5,
                )
        except gspread.exceptions.WorksheetNotFound:
            logger.info("Criando aba '%s'", Config.TAB_CLASSIFICACAO)
            ws = self.spreadsheet.add_worksheet(
                title=Config.TAB_CLASSIFICACAO,
                rows=total_rows + 10,
                cols=total_cols + 5,
            )

        self._call(ws.clear)
        sheet_id = ws.id

        # Remove gridlines
        requests = [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"hideGridlines": True},
                },
                "fields": "gridProperties.hideGridlines",
            }
        }]

        for idx, liga in enumerate(ligas_ordenadas):
            c0 = idx * (COLS + ESPACO)
            c1 = c0 + COLS - 1
            n = len(classificacao[liga])

            # Titulo
            requests.append({
                "updateCells": {
                    "rows": [{"values": [{"userEnteredValue": {"stringValue": liga}}]}],
                    "fields": "userEnteredValue",
                    "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": c0},
                }
            })

            # Merge titulo
            requests.append({
                "mergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0, "endRowIndex": 1,
                        "startColumnIndex": c0, "endColumnIndex": c1 + 1,
                    },
                    "mergeType": "MERGE_ALL",
                }
            })

            # Formatacao titulo
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0, "endRowIndex": 1,
                        "startColumnIndex": c0, "endColumnIndex": c1 + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": C_HDR_BG,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "textFormat": {
                                "foregroundColor": C_HDR_FG,
                                "bold": True, "fontSize": 11, "fontFamily": "Arial",
                            },
                            "padding": {"top": 6, "bottom": 6},
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            })

            # Header formato
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1, "endRowIndex": 2,
                        "startColumnIndex": c0, "endColumnIndex": c1 + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.22, "green": 0.28, "blue": 0.36},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "textFormat": {
                                "foregroundColor": C_HDR_FG,
                                "bold": True, "fontSize": 9, "fontFamily": "Arial",
                            },
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            })

            # Dados formato
            if n > 0:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2, "endRowIndex": 2 + n,
                            "startColumnIndex": c0, "endColumnIndex": c1 + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "borders": BORDAS_TODAS,
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                                "textFormat": {"fontSize": 9, "fontFamily": "Arial"},
                                "padding": {"top": 3, "bottom": 3, "left": 4, "right": 4},
                            }
                        },
                        "fields": "userEnteredFormat",
                    }
                })

                # Jogador alinhado esquerda
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2, "endRowIndex": 2 + n,
                            "startColumnIndex": c0 + 1, "endColumnIndex": c0 + 2,
                        },
                        "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                        "fields": "userEnteredFormat.horizontalAlignment",
                    }
                })

                # Zebrado
                for i in range(n):
                    cor = C_ZEBRA if i % 2 == 0 else C_WHITE
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 2 + i, "endRowIndex": 3 + i,
                                "startColumnIndex": c0, "endColumnIndex": c1 + 1,
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": cor}},
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    })

            # Larguras
            larguras = [35, 180, 40, 40, 40, 40, 40, 40, 40, 40]
            for ci, w in enumerate(larguras):
                requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": c0 + ci,
                            "endIndex": c0 + ci + 1,
                        },
                        "properties": {"pixelSize": w},
                        "fields": "pixelSize",
                    }
                })

        # Freeze
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 2}},
            "fields": "gridProperties.frozenRowCount",
        }})

        self.spreadsheet.batch_update({"requests": requests})
        time.sleep(3)

        # --- batch 2: escreve TUDO de uma vez ------------------------------
        # Monta matriz completa com headers e dados de todas as ligas
        all_data = []
        for row_idx in range(total_rows):
            row = []
            for idx, liga in enumerate(ligas_ordenadas):
                c0 = idx * (COLS + ESPACO)
                n = len(classificacao[liga])

                if row_idx == 0:
                    # Linha do titulo (escrita via updateCells, aqui fica vazio)
                    row.extend([""] * COLS)
                elif row_idx == 1:
                    # Headers
                    row.extend(HEADERS_CLASSIFICACAO)
                elif 2 <= row_idx < 2 + n:
                    # Dados
                    row.extend(classificacao[liga][row_idx - 2])
                else:
                    # Vazio abaixo dos dados
                    row.extend([""] * COLS)

                # Coluna de espaco entre blocos
                if idx < len(ligas_ordenadas) - 1:
                    row.append("")

            all_data.append(row)

        # Escreve tudo em uma unica chamada
        end_col_all = self._col_letter(total_cols - 1)
        self._call(ws.update, f"A1:{end_col_all}{total_rows}", all_data)
        time.sleep(3)

        # --- batch 3: graficos de colunas ----------------------------------
        chart_requests = []
        CORES_GRAFICO = [
            {"red": 0.20, "green": 0.45, "blue": 0.75},
            {"red": 0.90, "green": 0.35, "blue": 0.25},
            {"red": 0.30, "green": 0.70, "blue": 0.40},
            {"red": 0.85, "green": 0.65, "blue": 0.15},
            {"red": 0.55, "green": 0.35, "blue": 0.65},
            {"red": 0.25, "green": 0.65, "blue": 0.70},
            {"red": 0.75, "green": 0.45, "blue": 0.20},
            {"red": 0.40, "green": 0.55, "blue": 0.80},
        ]

        for idx, liga in enumerate(ligas_ordenadas):
            c0 = idx * (COLS + ESPACO)
            n = len(classificacao[liga])
            if n < 1:
                continue

            data_start_row = 2
            data_end_row = 2 + n

            # Linha onde comeca o grafico (2 linhas abaixo dos dados)
            chart_row = data_end_row + 2

            chart_spec = {
                "title": f"{liga} - Pontuacao",
                "basicChart": {
                    "chartType": "COLUMN",
                    "legendPosition": "BOTTOM_LEGEND",
                    "axis": [
                        {"position": "BOTTOM_AXIS", "title": "Jogador"},
                        {"position": "LEFT_AXIS", "title": "Pontos"},
                    ],
                    "domains": [{
                        "domain": {
                            "sourceRange": {
                                "sources": [{
                                    "sheetId": sheet_id,
                                    "startRowIndex": data_start_row,
                                    "endRowIndex": data_end_row,
                                    "startColumnIndex": c0 + 1,
                                    "endColumnIndex": c0 + 2,
                                }]
                            }
                        }
                    }],
                    "series": [{
                        "series": {
                            "sourceRange": {
                                "sources": [{
                                    "sheetId": sheet_id,
                                    "startRowIndex": data_start_row,
                                    "endRowIndex": data_end_row,
                                    "startColumnIndex": c0 + 2,
                                    "endColumnIndex": c0 + 3,
                                }]
                            }
                        },
                        "color": CORES_GRAFICO[idx % len(CORES_GRAFICO)],
                    }],
                    "headerCount": 0,
                },
                "titleTextFormat": {
                    "fontSize": 11,
                    "bold": True,
                    "fontFamily": "Arial",
                },
            }

            chart_requests.append({
                "addChart": {
                    "chart": {
                        "spec": chart_spec,
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": sheet_id,
                                    "rowIndex": chart_row,
                                    "columnIndex": c0,
                                },
                                "offsetXPixels": 0,
                                "offsetYPixels": 0,
                                "widthPixels": 450,
                                "heightPixels": 250,
                            }
                        },
                    }
                }
            })

        if chart_requests:
            self.spreadsheet.batch_update({"requests": chart_requests})

        logger.info("Classificacao atualizada (%d ligas)", len(ligas_ordenadas))
