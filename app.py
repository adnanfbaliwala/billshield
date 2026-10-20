import os
import json
import gradio as gr
from pypdf import PdfReader
from groq import Groq
from supabase import create_client

db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
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
Credits, discounts, payments and rebates are NEGATIVE numbers.
"charges" holds only the lines that make up the current month's total.
Never include subtotal, running total or "total of the above" lines
in "charges". Only list the individual charges.
If the previous balance already appears as a line inside "charges",
set "previous_unpaid" to 0 so it is not counted twice.
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

MESSAGE_RULES = """You write short, polite complaint emails about
bills, in the customer's voice. The bill may be for electricity,
broadband, mobile, a credit card or anything else.

Use ONLY the figures given to you. Never state a number that is
not in the facts below. Never calculate anything.
Do not invent an error. If the arithmetic checks out, say so and
ask about what the customer is actually worried about.
Always end by asking for a complaint reference number.
All amounts are Indian rupees. Write them as Rs. 2,386.80 — never
use a euro, dollar or pound sign.
Keep it under 150 words. No greeting line with a name. Plain text."""


def write_message(facts):
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": MESSAGE_RULES},
            {"role": "user", "content": facts},
        ],
    )
    return response.choices[0].message.content

EXPLAIN_RULES = """You explain bills in plain English, in three
sentences or less. Use ONLY the figures given. Never calculate.
If the person asked a question, answer it directly from the bill.
If the bill does not say, say that it does not say.
Amounts are Indian rupees, written as Rs. 200."""


def explain(facts):
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": EXPLAIN_RULES},
            {"role": "user", "content": facts},
        ],
    )
    return response.choices[0].message.content

def save_everything(data, summary, message, charges_total):
    bill_row = db.table("bills").insert({
        "company": data.get("company"),
        "bill_date": data.get("bill_date"),
        "current_total": data.get("current_total"),
        "other_charges": data.get("other_charges"),
        "previous_unpaid": data.get("previous_unpaid"),
        "amount_payable": data.get("amount_payable"),
        "summary": summary,
        "raw_json": data,
    }).execute()

    bill_id = bill_row.data[0]["id"]

    biggest_id = None
    biggest_amount = 0

    for charge in data.get("charges", []):
        label = str(charge.get("label") or "")
        amount = charge.get("amount") or 0
        row = db.table("line_items").insert({
            "bill_id": bill_id,
            "label": label,
            "normalised_label": label.lower().replace(" ", ""),
            "amount": amount,
            "units": charge.get("units"),
            "rate": charge.get("rate"),
            "checked": "checked",
        }).execute()
        if abs(amount) > biggest_amount:
            biggest_amount = abs(amount)
            biggest_id = row.data[0]["id"]

    db.table("messages").insert({
        "bill_id": bill_id,
        "line_item_id": biggest_id,
        "text": message,
    }).execute()

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

    mismatch = ("These do not match. This may be a reading problem rather "
                "than a billing error — check the printed bill.")

    lines.append("")
    lines.append("**Do the charges add up to what they say this month costs?**")
    lines.append("Charges add to " + str(round(total_of_lines, 2))
                 + ". Bill says " + str(current) + ".")
    if abs(total_of_lines - current) < 1:
        lines.append("Correct.")
    else:
        lines.append(mismatch)

    lines.append("")
    lines.append("**Does the total they are asking for add up?**")
    lines.append(str(current) + " + " + str(other) + " + " + str(previous)
                 + " = " + str(round(current + other + previous, 2))
                 + ". Bill asks for " + str(payable) + ".")
    if abs((current + other + previous) - payable) < 1:
        lines.append("Correct.")
    else:
        lines.append(mismatch)

    contact_lines = ["### Who to contact", ""]
    for c in data.get("contacts", []):
        email = str(c.get("email") or "")
        if "*" in email or email == "":
            continue
        contact_lines.append("- **" + str(c.get("name")) + "** — " + email)

    if len(contact_lines) == 2:
        contact_lines.append("This bill does not print a complaint address. "
                             "Check the company's website or the back of the "
                             "statement, then paste it into your email.")

    facts = "Company: " + str(data.get("company"))
    facts = facts + "\nBill month: " + str(data.get("bill_date"))
    facts = facts + "\nCharges this month: " + str(current)
    facts = facts + "\nLate fees or adjustments: " + str(other)
    facts = facts + "\nUnpaid from earlier months: " + str(previous)
    facts = facts + "\nTotal amount demanded: " + str(payable)
    facts = facts + "\nOur own check of the charges came to: " + str(round(total_of_lines, 2))
    facts = facts + "\nWhat the customer says is bothering them: " + str(complaint)

    summary = explain(facts)
    lines.insert(1, summary)
    lines.insert(2, "")

    message = write_message(facts)
    save_everything(data, "\n".join(lines), message, total_of_lines)

    return "\n".join(lines), "\n".join(contact_lines), message


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
        msg = gr.Textbox(label="5. Your message to the company — edit it or just copy and send",
                     lines=10, interactive=True)

    btn.click(check_bill, [bill, complaint], [found, contacts, msg])

    def reset_outputs(file):
        return "", "", "", ""

    bill.change(reset_outputs, bill, [found, contacts, msg, complaint])

app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
