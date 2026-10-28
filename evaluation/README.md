# Altimate V1 Evaluation Policy

`PASS / REVIEW` is an operational workflow status, **not** the primary quality metric.

Use the batch `_evaluation_scorecard.json` for:
- useful fact count
- priority fact coverage
- PDF calls per technical product
- PDF second-call rate (0% in V2.1)
- expensive writer escalation rate (0% in V2.1)
- factual safety status
- naturalness / tone diagnostics
- SEO score, density and word count
- estimated cost per product

For extraction accuracy, create manually adjudicated Golden files in a separate folder:

```json
{
  "part_number": "EXAMPLE",
  "facts": [
    {"parameter":"Operating supply voltage","value_text":"4.5 to 18","unit":"V"}
  ]
}
```

Then run:

```cmd
python run_evaluation.py outputs --golden-dir evaluation\golden
```

Golden Precision / Recall are meaningful only when the reference facts have been manually verified against the datasheet. Do not manufacture ground truth from the model output itself.
