import gradio as gr

def check_bill(file, complaint):
    found = "Upload working. Analysis not wired up yet."
    contacts = "Contacts will appear here."
    message = "Complaint message will appear here."
    return found, contacts, message

with gr.Blocks(title="BillShield") as app:
    gr.Markdown("# BillShield\nFind out what your bill actually says")

    bill = gr.File(label="1. Upload your bill", file_types=[".pdf", ".png", ".jpg"])
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

app.launch()
