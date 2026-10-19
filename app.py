import os
import json
import gradio as gr
from pypdf import PdfReader
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

INSTRUCTIONS = """You read utility and telecom bills.
Return ONLY JSON in this exact shape:

{
  "company": "name printed on the bill",
  "bill_date": "the bill month or date",
  "charges": [
    {"label": "name of charge as printed", "amount": number,
     "units": number or null, "rate": number or null}
  ],
  "current_total": number,
  "other_charges": number,
  "previous_unpaid": number,
  "amount_payable": number,
  "contacts": [
    {"name": "what the bill calls it", "email": "address"}
  ]
}

RULES
Copy every number exactly as printed. Never calculate anything.
"amount" is the rupee figure in the amount column, never the rate
per unit. Put the rate per unit in "rate" and the number of units
in "units".
Credits, discounts and rebates are NEGATIVE numbers.
"charges" holds only the lines that make up the current month's total.
Late fees, interest and adjustments shown separately go in
"other_charges" as a single number, 0 if there are none.
"contacts" holds only the company's own helpline, grievance,
consumer forum or ombudsman addresses. Never the customer's own
email. Never an address containing asterisks.
If a value is not on the bill, use null."""


def read_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        text = text + (page.extract_text() or "")
    return text


def ask_groq(bill_text):
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": bill_text[:12000]},
        ],
    )
    return json.loads(response.choices[0].message.content)


def check_bill(file, complaint):
    if file is None:
        return "Please upload a PDF bill first.", "", ""

    text = read_pdf(file)
    if text.strip() == "":
        return "This PDF has no readable text. It may be a scan.", "", ""

    data = ask_groq(text)

    lines = ["### " + str(data.get("company", "Your bill")), ""]
    lines.append("| Charge | Amount |")
    lines.append("|---|---|")

    total_of_lines = 0
    for charge in data.get("charges", []):
        amount = charge.get("amount") or 0
        total_of_lines = total_of_lines + amount
        lines.append("| " + str(charge.get("label")) + " | " + str(amount) + " |")

    current = data.get("current_total") or 0
    other = data.get("other_charges") or 0
    previous = data.get("previous_unpaid") or 0
    payable = data.get("amount_payable") or 0

    lines.append("")
    lines.append("**Check 1 — do the charges add up to the month's total?**")
    lines.append("Charges add to " + str(round(total_of_lines, 2))
                 + ". Bill says " + str(current) + ".")
    if abs(total_of_lines - current) < 1:
        lines.append("Correct.")
    else:
        lines.append("These do not match.")

    lines.append("")
    lines.append("**Check 2 — does the amount asked for add up?**")
    lines.append(str(current) + " + " + str(other) + " + " + str(previous)
                 + " = " + str(round(current + other + previous, 2))
                 + ". Bill asks for " + str(payable) + ".")
    if abs((current + other + previous) - payable) < 1:
        lines.append("Correct.")
    else:
        lines.append("These do not match.")

    contact_lines = ["### Who to contact", ""]
    for c in data.get("contacts", []):
        email = str(c.get("email") or "")
        if "*" in email or email == "":
            continue
        contact_lines.append("- **" + str(c.get("name")) + "** — " + email)

    return "\n".join(lines), "\n".join(contact_lines), ""


with gr.Blocks(title="BillShield") as app:
    gr.Markdown("# BillShield\nFind out what your bill actually says")

    bill = gr.File(label="1. Upload your bill (PDF only)",
                   file_types=[".pdf"], type="filepath")
    complaint = gr.Textbox(label="2. What's bothering you about it?",
                           placeholder="Feels too high. I live alone, no AC.",
                           lines=3)
    btn = gr.Button("Check my bill", variant="primary")

    found = gr.Markdown(label="3. What we found")
    contacts = gr.Markdown(label="4. Who to contact")
    msg = gr.Textbox(label="5. Your complaint", lines=10, interactive=True)

    btn.click(check_bill, [bill, complaint], [found, contacts, msg])

app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
