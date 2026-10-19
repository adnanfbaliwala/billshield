import os
import gradio as gr
from pypdf import PdfReader

def check_bill(file, complaint):
    if file is None:
        return "Please upload a PDF bill first.", "", ""

    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text = text + (page.extract_text() or "")

    if text.strip() == "":
        return "This PDF has no readable text. It may be a scan.", "", ""

    found = "Read " + str(len(reader.pages)) + " pages.\n\n" + text[:3000]
    return found, "", ""

with gr.Blocks(title="BillShield") as app:
    gr.Markdown("# BillShield\nFind out what your bill actually says")

    bill = gr.File(
        label="1. Upload your bill (PDF only)",
        file_types=[".pdf"],
        type="filepath",
    )
    complaint = gr.Textbox(
        label="2. What's bothering you about it?",
        placeholder="Feels too high. I live alone, no AC.",
        lines=3,
    )
    btn = gr.Button("Check my bill", variant="primary")

    found = gr.Markdown(label="3. What we found")
    contacts = gr.Markdown(label="4. Who to contact")
    msg = gr.Textbox(label="5. Your complaint", lines=10, interactive=True)

    btn.click(check_bill, [bill, complaint], [found, contacts, msg])

app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
