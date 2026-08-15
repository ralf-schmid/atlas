# F116 — Assetklasse am Paar-Format statt an einer Ticker-Liste

Status: live auf der Box (15.08.2026)
Datum: 2026-08-15
Phase: 5 (Wettbewerbskennzahl, wirkt auf F083/F104/F114)
Auslöser: Ralf, nach dem Fund in [F114](F114-volumen-penalty-iex-massstab.md) §5.1

## 1. Zieldefinition

Der Slippage-Malus entscheidet über `slippage._asset_class`, ob ein Instrument
den Aktien- oder den Krypto-Spread bekommt (5 vs. 15 bps) und seit F114 auch,
welcher Volumen-Deckungsgrad gilt. Diese Entscheidung hing an einer gepflegten
Ticker-Liste in `config/review.yaml` und einem Substring-Vergleich.

Das ist zweimal schiefgegangen bzw. beinahe:

1. **Die Liste ging still veraltet.** ADR-0016 hat CRYPTORs Universum von drei
   auf zehn Paare erweitert; **AVAX, AAVE, UNI und LINK** fehlten in der Liste
   und bekamen den Aktien-Spread — seit F114 zusätzlich den Aktien-Deckungsgrad
   auf ein Börsenvolumen, für das er nicht gilt.
2. **Die Reparatur machte die Heuristik gefährlicher.** Um die vier Paare
   aufzunehmen, mussten kurze Fragmente wie `UNI` und `LINK` in die Liste. Ein
   Substring-Vergleich trifft damit jeden Aktien-Ticker, der sie enthält —
   `LINK`, `UNI`, `ADAP`, `SOLV`, `BTCS` sind reale US-Ticker. Am 15.08.2026 war
   zufällig keiner im Universum; das ist Glück, kein Entwurf.

Der Backtest löst dasselbe Problem seit F114 §5.1 strukturell über die
Paar-Notation (`backtest.spec.symbol_asset_class`). Dieses Feature zieht den
Live-Pfad nach.

## 2. Warum nicht einfach „enthält einen Schrägstrich"

Der Backtest kann sich das leisten, weil er ausschließlich `market_bar.symbol`
sieht — von Alpaca erzeugt und sauber. `slippage._asset_class` wird dagegen mit
**`decision.instrument`** aufgerufen, und das ist LLM-geschriebener Freitext. In
der produktiven Tabelle stehen tatsächlich:

```
SEAGATE/QCOM      NUKE... N/A      Boost Run Inc.      SCHNEIDER_ELECTRIC
```

`SEAGATE/QCOM` würde bei einer reinen Slash-Prüfung als Krypto gelten und den
dreifachen Spread bezahlen. Deshalb muss auch die Quote-Währung passen:

```python
_CRYPTO_PAIR = re.compile(r"^[A-Z0-9]{2,10}/(USD|USDT|USDC|USDG|BTC|ETH)$")
```

Kein Aktien-Ticker-Paar erfüllt das. Die Klassifikation braucht damit **keine
Config mehr** — Config bestimmt nur noch, wie die Klasse bepreist wird.

## 3. Kritische Betrachtung

| Invariante | Berührt? | Umgang |
|---|---|---|
| #10 Fairness | ja | Dieselbe Regel für alle Personas. Sie korrigiert eine Verzerrung, die bisher nur CRYPTOR getroffen hätte. |
| #1 Risk-Gate | nein | Keine Order-Entscheidung. |
| Wertung mitten in der Saison | **nein, nachweisbar** | Siehe §5. |

**Rückwärtskompatibilität:** ein Krypto-Symbol ohne Schrägstrich (`BTCUSD`) gilt
jetzt als Aktie. Geprüft: dieses Format existiert in `decision`, `market_bar` und
`position_snapshot` **nirgends** — real ist Krypto immer `BASE/USD`. Der einzige
Fundort war ein Testfixture, das entsprechend auf `BTC/USD` umgestellt wurde.

## 4. Testdefinition (vor der Umsetzung geschrieben)

In `tests/review/test_slippage.py`, Klasse `TestAssetClassification`:

1. Alle zehn Paare aus CRYPTORs Charter gelten als Krypto.
2. Die realen Aktien-Ticker `LINK`, `UNI`, `ADAP`, `SOLV`, `BTCS`, `DOTM`
   gelten als Aktien — genau die Fälle, die die alte Liste falsch getroffen hätte.
3. Freitext-Instrumente aus der Produktion (`SEAGATE/QCOM`, `NUKE... N/A`,
   `Boost Run Inc.`, leerer String) sind keine Krypto.
4. Die Klassifikation funktioniert ohne Config; Config bepreist nur.
5. Groß-/Kleinschreibung und Leerzeichen sind egal.
6. Der Anti-Drift-Test gegen CRYPTORs Charter bleibt — er hält jetzt für jedes
   Paar, das der Charter je bekommt, statt nur für die gepflegten.

## 5. Verifikation

- **1156 passed**, Coverage 91,67 % (Gate 90), risk/broker-Branch 100 %,
  `ruff`, `ruff format`, `mypy src` sauber.
- **Laufende Saison unverändert:** alle gefüllten Orders sind Aktien mit
  gewöhnlichen Tickern; deren Klassifikation ist unter alter wie neuer Regel
  `equities`. Leaderboard-Malus vor und nach dem Deploy identisch (§5 Tabelle in
  F114 gilt unverändert weiter).
- CRYPTOR hat bisher nicht gehandelt, der Krypto-Zweig ist also noch nie
  live gelaufen — die Korrektur wirkt vorbeugend.

## 6. Rollback

Revert des Commits. Kein Schema-Change, keine Migration, keine Datenänderung.
Der entfernte Config-Block `slippage.crypto_symbols` wird von keinem Code mehr
gelesen; ein Revert bringt ihn samt Leser zurück.
