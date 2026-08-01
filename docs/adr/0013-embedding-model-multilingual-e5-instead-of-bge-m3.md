# ADR-0013: `multilingual-e5-large` statt bge-m3 als lokales Embedding-Modell

* Status: accepted
* Deciders: Ralf Schmid (Auftrag), Claude (Modellwahl mangels Alternative)
* Datum: 2026-08-01
* Betrifft ARCHITECTURE.md **§3.3.1**, CLAUDE.md („lokal nur Embeddings (bge-m3)")

## Kontext

F098 (Lessons-Rückfluss) braucht lokale Embeddings. CLAUDE.md und
ARCHITECTURE.md §3.3.1 nennen dafür ausdrücklich **bge-m3**.

Als Laufzeit wurde `fastembed` gewählt statt `sentence-transformers`: es rechnet
über onnxruntime statt torch und spart damit ~2 GB Image auf einer NAS. Dabei
zeigte sich:

```
ValueError: Model BAAI/bge-m3 is not supported in TextEmbedding.
```

`fastembed` bietet bge-m3 schlicht nicht an.

## Betrachtete Optionen

| Option | Dim | Größe | Bewertung |
|---|---|---|---|
| `sentence-transformers` + bge-m3 | 1024 | ~2,2 GB + torch | erfüllt CLAUDE.md wörtlich, zieht aber torch (~800 MB) zusätzlich ins Image |
| `intfloat/multilingual-e5-large` | 1024 | 2,24 GB | mehrsprachig, gleiche Dimension, kein torch |
| `paraphrase-multilingual-mpnet-base-v2` | 768 | 1,0 GB | kleiner, aber andere Dimension → andere Migration |
| englischsprachiges Modell (bge-small) | 384 | 0,22 GB | **verworfen**: die Lessons sind deutsch, das würde Retrieval still verschlechtern |

## Entscheidung

**`intfloat/multilingual-e5-large`.**

Begründung: gleiche Ausgabebreite wie bge-m3 (1024, die Migration bleibt gültig),
gleiche Größenklasse, ebenfalls mehrsprachig — und ohne torch im Image. Der Zweck
der CLAUDE.md-Regel ist „lokale Embeddings, keine lokalen LLMs im Trading-Pfad";
der ist vollständig erfüllt, nur der konkrete Modellname weicht ab.

## Konsequenzen

* Die Dimension 1024 steht fest in `review.lessons_embedding`. Ein Modellwechsel
  ist deshalb eine Migration, kein Config-Schalter — bewusst so.
* e5-Modelle sind auf ein asymmetrisches `query:`/`passage:`-Präfix trainiert.
  Da hier Text gegen Text verglichen wird (Lesson vs. aktuelle Lage), nutzen
  **beide** Seiten `query:`; das Mischen der Präfixe wäre der eigentliche Fehler.
* ~2,2 GB Modell-Download beim ersten Lauf, gecached über das Volume
  `./data/models` — ohne das lädt jeder Container-Neustart erneut.
* Sollte `fastembed` bge-m3 später aufnehmen, ist der Wechsel ein Einzeiler plus
  Re-Embedding der bestehenden Zeilen (gleiche Dimension).
