#!/usr/bin/env python3
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

from admin_audit import approve_item, attach_manual_datasheet, choose_no_datasheet_after_web_error, disapprove_item, list_audit_items, accept_rejected_image
from orchestrator.engine import IntegratedOrchestrator
from orchestrator.events import EventLogger
from reporting.excel_report import generate_report
from core.category_registry import load_registry
from core.category_management import add_category, remove_category, active_categories, CategoryAlreadyExists


# Statuses that allow a user-supplied, exact-PN datasheet PDF in Audit.
# An unsuccessful search must never conceal the admin recovery control.
def can_attach_manual_datasheet(part_number: str, datasheet_status: str) -> bool:
    return bool(str(part_number or '').strip()) and str(datasheet_status or '').strip().casefold() in {
        'manual_required', 'not_found_confirmed', 'identity_found_unresolved', 'failed', 'web_error', 'sales_only_no_datasheet',
    }


class AuditWindow(tk.Toplevel):
    def __init__(self, parent: "PipelineUI"):
        super().__init__(parent.root)
        self.parent_ui = parent
        self.project_root = parent.project_root
        self.items: list[dict] = []
        self.index = 0
        self._photos = []
        self.issue_vars: dict[str, tk.BooleanVar] = {}
        self.reviewed_in_session: set[str] = set()
        self.session_order: list[str] = []
        self.title("Catalog Automation Agent — Audit")
        self.geometry("1240x700")
        self.minsize(1080, 620)
        self.transient(parent.root)

        self.status_var = tk.StringVar(value="")
        self.counter_var = tk.StringVar(value="")
        self.message_var = tk.StringVar(value="")

        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        self.status_label = tk.Label(top, textvariable=self.status_var, font=("Segoe UI", 14, "bold"))
        self.status_label.pack(side="left")
        ttk.Label(top, textvariable=self.counter_var, font=("Segoe UI", 9)).pack(side="left", padx=14)
        ttk.Label(top, text="Enter = Approve & Next", font=("Segoe UI", 9)).pack(side="left", padx=10)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right", padx=4)
        ttk.Label(top, text="Filter:").pack(side="left", padx=(12, 3))
        self.audit_filter_var = tk.StringVar(value="All")
        self.audit_filter = ttk.Combobox(top, textvariable=self.audit_filter_var,
            state="readonly", width=18, values=["All", "Not Approved", "Rejected Images", "Missing Final", "Needs Audit", "Datasheet web_error"])
        self.audit_filter.pack(side="left", padx=3)
        self.audit_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh(keep_current=False))
        ttk.Label(top, text="PN:").pack(side="left", padx=(8, 2))
        self.audit_search_var = tk.StringVar(value="")
        self.audit_search = ttk.Entry(top, textvariable=self.audit_search_var, width=18)
        self.audit_search.pack(side="left", padx=2)
        self.audit_search.bind("<Return>", lambda e: self.refresh(keep_current=False))
        ttk.Button(top, text="Find", command=lambda: self.refresh(keep_current=False)).pack(side="left", padx=2)

        images = ttk.Frame(self, padding=(8, 0, 8, 4))
        images.pack(fill="x")
        self.original_frame = ttk.Labelframe(images, text="Original", padding=4)
        self.original_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.final_frame = ttk.Labelframe(images, text="Final / Prepared", padding=4)
        self.final_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.original_label = ttk.Label(self.original_frame, anchor="center")
        self.original_label.pack(fill="both", expand=True)
        self.final_label = ttk.Label(self.final_frame, anchor="center")
        self.final_label.pack(fill="both", expand=True)

        details = ttk.Labelframe(self, text="Pipeline Status", padding=8)
        details.pack(fill="x", padx=8, pady=(0, 4))
        self.detail_vars = {
            "part_number": tk.StringVar(value="-"),
            "source_reference": tk.StringVar(value="-"),
            "admin_status": tk.StringVar(value="-"),
            "datasheet_found": tk.StringVar(value="-"),
            "datasheet_status": tk.StringVar(value="-"),
            "datasheet_pdf": tk.StringVar(value="-"),
            "seo_score": tk.StringVar(value="-"),
            "seo_status": tk.StringVar(value="-"),
            "keyword_density": tk.StringVar(value="-"),
            "word_count": tk.StringVar(value="-"),
            "structure_safety": tk.StringVar(value="-"),
            "semantic_tone": tk.StringVar(value="-"),
        }
        details_grid = ttk.Frame(details)
        details_grid.pack(fill="x")
        detail_rows = [
            ("Part Number", "part_number", "Datasheet found", "datasheet_found"),
            ("Source reference", "source_reference", "Datasheet status", "datasheet_status"),
            ("Admin status", "admin_status", "Datasheet PDF", "datasheet_pdf"),
            ("SEO score", "seo_score", "SEO status", "seo_status"),
            ("Keyword density", "keyword_density", "Word count", "word_count"),
            ("Structure / safety", "structure_safety", "Semantic / tone", "semantic_tone"),
        ]
        for row_idx, (label1, key1, label2, key2) in enumerate(detail_rows):
            ttk.Label(details_grid, text=label1 + ":", font=("Segoe UI", 9, "bold")).grid(row=row_idx, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(details_grid, textvariable=self.detail_vars[key1], font=("Consolas", 9)).grid(row=row_idx, column=1, sticky="w", padx=(0, 12), pady=2)
            ttk.Label(details_grid, text=label2 + ":", font=("Segoe UI", 9, "bold")).grid(row=row_idx, column=2, sticky="w", padx=(8, 6), pady=2)
            ttk.Label(details_grid, textvariable=self.detail_vars[key2], font=("Consolas", 9)).grid(row=row_idx, column=3, sticky="w", pady=2)
        details_grid.columnconfigure(1, weight=1)
        details_grid.columnconfigure(3, weight=1)

        self.audit_diagnostic_text = tk.StringVar(value='')
        ttk.Label(details, textvariable=self.audit_diagnostic_text, foreground='#b42318',
                  wraplength=1120, justify='left').pack(fill='x', pady=(5, 3))

        self.manual_ds_frame = ttk.Frame(details)
        self.manual_ds_label = tk.Label(
            self.manual_ds_frame,
            text="Drop datasheet PDF here",
            relief="groove",
            bd=1,
            padx=10,
            pady=4,
            fg="#175cd3",
        )
        self.manual_ds_label.pack(side="left", fill="x", expand=True)
        ttk.Button(self.manual_ds_frame, text="Browse PDF", command=self._browse_manual_datasheet).pack(side="left", padx=(8, 0))
        self.no_datasheet_button = ttk.Button(self.manual_ds_frame, text="Datasheet Doesn't Exist",
            command=self._choose_no_datasheet_after_web_error)
        # Only web_error products show this choice; no automatic approval.
        if DND_AVAILABLE and hasattr(self.manual_ds_label, "drop_target_register"):
            try:
                self.manual_ds_label.drop_target_register(DND_FILES)
                self.manual_ds_label.dnd_bind("<<Drop>>", self._on_datasheet_drop)
            except Exception:
                pass

        actions = ttk.Labelframe(self, text="Admin Decision", padding=8)
        actions.pack(fill="x", padx=8, pady=(0, 4))
        button_row = ttk.Frame(actions)
        button_row.pack(fill="x")
        self.approve_btn = ttk.Button(button_row, text="Approve", command=self.approve)
        self.approve_btn.pack(side="left", padx=(0, 8))
        self.disapprove_btn = ttk.Button(button_row, text="Disapprove", command=self.show_disapprove)
        self.disapprove_btn.pack(side="left")
        self.accept_image_btn = ttk.Button(button_row, text="Accept Rejected Image", command=self.accept_image)
        self.accept_image_btn.pack(side="left", padx=(10, 0))
        ttk.Label(button_row, textvariable=self.message_var).pack(side="left", padx=18)

        self.issue_frame = ttk.Frame(actions)
        # Wrong PN row: entry intentionally sits directly beside the checkbox.
        row1 = ttk.Frame(self.issue_frame)
        row1.pack(fill="x", pady=2)
        self.issue_vars["wrong_part_number"] = tk.BooleanVar(value=False)
        self.wrong_pn_cb = ttk.Checkbutton(
            row1, text="wrong part number", variable=self.issue_vars["wrong_part_number"], command=self._wrong_pn_changed
        )
        self.wrong_pn_cb.pack(side="left")
        self.correct_pn_label = ttk.Label(row1, text="enter the right PN:")
        self.correct_pn_entry = ttk.Entry(row1, width=28)

        row2 = ttk.Frame(self.issue_frame); row2.pack(fill="x", pady=2)
        self.issue_vars["image_regeneration_needed"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="image regeneration needed", variable=self.issue_vars["image_regeneration_needed"]).pack(side="left")

        row3 = ttk.Frame(self.issue_frame); row3.pack(fill="x", pady=2)
        self.issue_vars["wrong_data_sheet"] = tk.BooleanVar(value=False)
        self.wrong_ds_cb = ttk.Checkbutton(row3, text="wrong data sheet", variable=self.issue_vars["wrong_data_sheet"])
        self.wrong_ds_cb.pack(side="left")

        row4 = ttk.Frame(self.issue_frame); row4.pack(fill="x", pady=2)
        self.issue_vars["seo_content_regeneration_needed"] = tk.BooleanVar(value=False)
        self.seo_cb = ttk.Checkbutton(row4, text="SEO content regeneration needed", variable=self.issue_vars["seo_content_regeneration_needed"])
        self.seo_cb.pack(side="left")

        submit_row = ttk.Frame(self.issue_frame); submit_row.pack(fill="x", pady=(8, 0))
        ttk.Button(submit_row, text="Confirm Disapprove & Next", command=self.submit_disapproval).pack(side="left")
        ttk.Label(
            submit_row,
            text="Audit decisions are saved now; API reprocessing runs through the normal checkpoint/recovery pipeline on the next Start.",
        ).pack(side="left", padx=12)

        nav = ttk.Frame(self, padding=(8, 0, 8, 8))
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="◀ Previous", command=self.prev_item).pack(side="left")
        ttk.Button(nav, text="Next ▶", command=self.next_item).pack(side="right")

        self.bind("<Return>", self._on_enter_approve)
        self.refresh()
        self.session_order = [str(x.get("source_reference") or "") for x in self.items]

    def _filtered_audit_items(self):
        items = list_audit_items(self.project_root)
        mode = self.audit_filter_var.get()
        query = self.audit_search_var.get().strip().casefold()
        if mode == "Not Approved":
            items = [x for x in items if not bool(x.get("admin_approved"))]
        elif mode == "Rejected Images":
            items = [x for x in items if any(d.get("code") == "IMAGE_IDENTITY_REJECTED" for d in x.get("diagnostics") or [])]
        elif mode == "Missing Final":
            items = [x for x in items if not x.get("final_path")]
        elif mode == "Needs Audit":
            items = [x for x in items if x.get("classification") == "AUDIT_NEEDED"]
        elif mode == "Datasheet web_error":
            items = [x for x in items if (x.get("datasheet") or {}).get("status") == "web_error"]
        if query:
            items = [x for x in items if query in (x.get("part_number") or "").casefold()
                     or query in (x.get("source_reference") or "").casefold()]
        return items

    def refresh(self, keep_current: bool = True):
        current_key = None
        if keep_current and self.items and 0 <= self.index < len(self.items):
            current_key = self.items[self.index].get("metadata_path")
        self.items = self._filtered_audit_items()
        if current_key:
            for i, item in enumerate(self.items):
                if item.get("metadata_path") == current_key:
                    self.index = i
                    break
            else:
                self.index = min(self.index, max(0, len(self.items) - 1))
        else:
            self.index = min(self.index, max(0, len(self.items) - 1))
        self._render()

    def _load_photo(self, path_text: str | None, max_size=(430, 220)):
        if not path_text:
            return None
        p = Path(path_text)
        if not p.exists():
            return None
        try:
            img = Image.open(p).convert("RGB")
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _set_image(self, label: ttk.Label, path_text: str | None, fallback: str):
        photo = self._load_photo(path_text)
        if photo:
            label.configure(image=photo, text="")
            self._photos.append(photo)
        else:
            label.configure(image="", text=fallback)

    def _render(self):
        self._photos = []
        self.message_var.set("")
        self.issue_frame.pack_forget()
        for var in self.issue_vars.values():
            var.set(False)
        self.correct_pn_entry.delete(0, "end")
        self.correct_pn_label.pack_forget()
        self.correct_pn_entry.pack_forget()
        self.wrong_ds_cb.configure(state="normal")
        self.seo_cb.configure(state="normal")
        self.no_datasheet_button.pack_forget()
        self.manual_ds_frame.pack_forget()
        self.audit_diagnostic_text.set('')
        self.accept_image_btn.configure(state="disabled")

        if not self.items:
            self.status_var.set("No products available for audit")
            self.status_label.configure(fg="#667085")
            self.counter_var.set("")
            self.original_label.configure(image="", text="No item")
            self.final_label.configure(image="", text="No item")
            self.approve_btn.configure(state="disabled")
            self.disapprove_btn.configure(state="disabled")
            return

        item = self.items[self.index]
        self.counter_var.set(f"{self.index + 1} / {len(self.items)}")
        if item["classification"] == "AUDIT_NEEDED":
            self.status_var.set("AUDIT NEEDED")
            self.status_label.configure(fg="#b42318")
        else:
            self.status_var.set("FINALIZED")
            self.status_label.configure(fg="#16803a")

        if item["classification"] == "AUDIT_NEEDED":
            diagnostics = item.get("diagnostics") or []
            self.message_var.set(" | ".join(x['code'] for x in diagnostics[:3]))
            self.audit_diagnostic_text.set('  •  '.join(
                f"{x['code']}: {x['detail']} → {x['action']}" for x in diagnostics[:4]))
            self.status_var.set("AUDIT NEEDED — " + str(item.get('title') or 'Check details')[:105])
        if any(x.get('code') == 'IMAGE_IDENTITY_REJECTED' for x in (item.get('diagnostics') or [])) and not item.get('candidate_path'):
            self.message_var.set("Rejected candidate PNG absent in output/; restore *_canvas.png or *_regen.png")
        self.accept_image_btn.configure(state="normal" if (
            item.get('candidate_path') and not item.get('final_path') and
            any(x.get('code') == 'IMAGE_IDENTITY_REJECTED' for x in (item.get('diagnostics') or []))
        ) else "disabled")
        self._set_image(self.original_label, item.get("original_path"), "Original image not found")
        visual = item.get("final_path") or item.get("candidate_path")
        self._set_image(self.final_label, visual, "Final/prepared image not available")

        ds = item["datasheet"]
        seo = item["seo"]
        ds_status = str(ds.get("status") or "")
        if can_attach_manual_datasheet(item.get("part_number"), ds_status):
            self.manual_ds_frame.pack(fill="x", pady=(6, 0))
            hint = "Drop datasheet PDF here"
            if ds_status == "manual_required":
                hint = "MANUAL REQUIRED — drop the exact datasheet PDF here"
            elif ds_status == "not_found_confirmed":
                hint = "No datasheet found — drop an exact PDF here if you have one"
            elif ds_status == "failed":
                hint = "DATASHEET SEARCH FAILED — attach the exact PDF to regenerate facts and SEO"
            self.manual_ds_label.configure(text=hint)
        density_target = seo.get("keyword_density_target") or {}
        wc_target = seo.get("word_count_target") or {}
        self.detail_vars["part_number"].set(str(item.get("part_number") or "[NOT CONFIRMED]"))
        self.detail_vars["source_reference"].set(str(item.get("source_reference") or "-"))
        self.detail_vars["admin_status"].set(str(item.get("admin_status") or "-"))
        if ds_status == "web_error":
            self.no_datasheet_button.pack(side="left", padx=(8, 0))
            self.manual_ds_label.configure(text="WEB ERROR — choose an exact PDF or continue without one")
        self.detail_vars["datasheet_found"].set("YES" if ds.get("found") else "NO")
        self.detail_vars["datasheet_status"].set(str(ds.get("status") or "-"))
        self.detail_vars["datasheet_pdf"].set(str(ds.get("pdf_name") or "-"))
        self.detail_vars["seo_score"].set(f"{seo.get('score') if seo.get('available') else '-'} / 100")
        self.detail_vars["seo_status"].set(f"{seo.get('seo_status') or '-'} | disp={seo.get('disposition') or '-'}")
        self.detail_vars["keyword_density"].set(
            f"{seo.get('keyword_density') if seo.get('available') else '-'} | target={density_target.get('min','-')}-{density_target.get('max','-')}"
        )
        self.detail_vars["word_count"].set(
            f"{seo.get('word_count') if seo.get('available') else '-'} | target={wc_target.get('min','-')}-{wc_target.get('max','-')}"
        )
        self.detail_vars["structure_safety"].set(f"{seo.get('structure_pass')} / {seo.get('fact_safety_pass')}")
        self.detail_vars["semantic_tone"].set(
            f"{seo.get('semantic_audit_status') or '-'} / {seo.get('tone_status') or '-'} | nat={seo.get('tone_naturalness') if seo.get('tone_naturalness') is not None else '-'}"
        )

        self.approve_btn.configure(state="normal" if item["classification"] == "FINALIZED" else "disabled")
        self.disapprove_btn.configure(state="normal")
        if not item.get("part_number"):
            # Problematic PN items naturally open with the relevant option ready.
            self.show_disapprove()
            self.issue_vars["wrong_part_number"].set(True)
            self._wrong_pn_changed()

    def show_disapprove(self):
        self.issue_frame.pack(fill="x", pady=(10, 0))

    def _wrong_pn_changed(self):
        selected = self.issue_vars["wrong_part_number"].get()
        if selected:
            self.issue_vars["wrong_data_sheet"].set(False)
            self.issue_vars["seo_content_regeneration_needed"].set(False)
            self.wrong_ds_cb.configure(state="disabled")
            self.seo_cb.configure(state="disabled")
            self.correct_pn_label.pack(side="left", padx=(12, 4))
            self.correct_pn_entry.pack(side="left")
            self.correct_pn_entry.configure(state="normal")
            self.correct_pn_entry.focus_set()
        else:
            self.wrong_ds_cb.configure(state="normal")
            self.seo_cb.configure(state="normal")
            self.correct_pn_label.pack_forget()
            self.correct_pn_entry.pack_forget()

    def _current_item(self):
        if not self.items or not (0 <= self.index < len(self.items)):
            return None
        return self.items[self.index]

    def _attach_manual_datasheet_path(self, path_text: str):
        item = self._current_item()
        if not item:
            return
        path = Path(path_text)
        try:
            result = attach_manual_datasheet(self.project_root, Path(item["metadata_path"]), path)
        except Exception as exc:
            messagebox.showerror("Datasheet attach failed", str(exc), parent=self)
            return
        current_ref = str(item.get("source_reference") or "")
        self._refresh_to_source(current_ref)
        self.message_var.set(f"{result['part_number']}: datasheet attached; Phase 3 will rebuild on next Start")

    def _choose_no_datasheet_after_web_error(self):
        item = self._current_item()
        if not item or str((item.get("datasheet") or {}).get("status")) != "web_error":
            messagebox.showerror("Unavailable", "This choice is only for web_error items", parent=self)
            return
        pn = str(item.get("part_number") or "")
        confirm = messagebox.askyesno(
            "Continue without datasheet?",
            f"{pn}: Online search failed. This does NOT prove the datasheet does not exist.\n"
            "Generate sales-only content without unverified electrical specifications?\n"
            "You must review and approve the result afterwards.",
            parent=self)
        if not confirm:
            return
        try:
            result = choose_no_datasheet_after_web_error(self.project_root, Path(item["metadata_path"]))
        except Exception as exc:
            messagebox.showerror("Sales-only decision failed", str(exc), parent=self)
            return
        current_ref = str(item.get("source_reference") or "")
        self._refresh_to_source(current_ref)
        self.message_var.set(f"{result['part_number']}: sales-only authorized; press Start to generate SEO")

    def accept_image(self):
        item = self._current_item()
        if not item or not item.get('candidate_path'):
            return
        pn = str(item.get('part_number') or '')
        if not messagebox.askyesno('Accept rejected candidate?',
            f'{pn}: You confirm that the shown candidate is the correct physical product, markings and leads.\n'
            'The AI rejection will stay in history. Add logo, compress to WebP and write Final without AI regeneration?', parent=self):
            return
        try:
            result = accept_rejected_image(self.project_root, Path(item['metadata_path']), candidate=Path(item['candidate_path']))
        except Exception as exc:
            messagebox.showerror('Accept Image failed', str(exc), parent=self)
            return
        ref = str(item.get('source_reference') or '')
        self._refresh_to_source(ref)
        self.message_var.set(f"Accepted: {result['part_number']} — WebP finalized. Run/resume remaining stages if needed.")

    def _browse_manual_datasheet(self):
        selected = filedialog.askopenfilename(parent=self, title="Select exact datasheet PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if selected:
            self._attach_manual_datasheet_path(selected)

    def _on_datasheet_drop(self, event):
        try:
            values = self.tk.splitlist(event.data)
        except Exception:
            values = [str(getattr(event, "data", ""))]
        pdfs = [x for x in values if str(x).lower().endswith(".pdf")]
        if len(pdfs) != 1:
            messagebox.showerror("Datasheet attach failed", "Drop exactly one PDF file", parent=self)
            return
        self._attach_manual_datasheet_path(pdfs[0])

    def _refresh_to_source(self, source_ref: str):
        self.items = self._filtered_audit_items()
        for i, candidate in enumerate(self.items):
            if str(candidate.get("source_reference") or "") == str(source_ref or ""):
                self.index = i
                self._render()
                return
        self.index = min(self.index, max(0, len(self.items) - 1))
        self._render()

    def _on_enter_approve(self, event=None):
        if not self.items:
            return "break"
        if str(self.approve_btn.cget("state")) == "disabled":
            return "break"
        focused = self.focus_get()
        if focused is self.correct_pn_entry:
            return None
        self.approve()
        return "break"

    def _advance_after_decision(self, reviewed_source_reference: str, success_message: str):
        """Move strictly forward in the audit-session order; never jump back to item 1."""
        reviewed_source_reference = str(reviewed_source_reference or "")
        self.reviewed_in_session.add(reviewed_source_reference)
        self.items = self._filtered_audit_items()
        by_ref = {str(x.get("source_reference") or ""): i for i, x in enumerate(self.items)}

        if not self.session_order:
            self.session_order = list(by_ref)
        try:
            current_pos = self.session_order.index(reviewed_source_reference)
        except ValueError:
            current_pos = -1

        next_ref = None
        for ref in self.session_order[current_pos + 1:]:
            if ref in by_ref and ref not in self.reviewed_in_session:
                next_ref = ref
                break

        if next_ref is not None:
            self.index = by_ref[next_ref]
            self._render()
            self.message_var.set(success_message)
            return

        # Never wrap to the first record. Keep the last reviewed item visible.
        if reviewed_source_reference in by_ref:
            self.index = by_ref[reviewed_source_reference]
        else:
            self.index = min(self.index, max(0, len(self.items) - 1))
        self._render()
        self.message_var.set(success_message + " | End of this audit sequence")

    def approve(self):
        if not self.items:
            return
        item = self.items[self.index]
        source_ref = str(item.get("source_reference") or "")
        try:
            result = approve_item(self.project_root, Path(item["metadata_path"]))
        except Exception as exc:
            messagebox.showerror("Approve failed", str(exc), parent=self)
            return
        self._advance_after_decision(
            source_ref,
            f"Approved → {Path(result['ready_bundle']).name} is ready for website upload",
        )

    def submit_disapproval(self):
        if not self.items:
            return
        item = self.items[self.index]
        source_ref = str(item.get("source_reference") or "")
        issues = [key for key, var in self.issue_vars.items() if var.get()]
        corrected = self.correct_pn_entry.get().strip() if "wrong_part_number" in issues else None
        try:
            result = disapprove_item(
                self.project_root,
                Path(item["metadata_path"]),
                issues,
                corrected_pn=corrected,
            )
        except Exception as exc:
            messagebox.showerror("Disapprove failed", str(exc), parent=self)
            return
        pn = result.get("part_number") or source_ref
        self._advance_after_decision(
            source_ref,
            f"{pn}: selected fixes queued for next Start",
        )

    def prev_item(self):
        if not self.items:
            return
        self.index = (self.index - 1) % len(self.items)
        self._render()

    def next_item(self):
        if not self.items:
            return
        self.index = (self.index + 1) % len(self.items)
        self._render()


class PipelineUI:
    def __init__(self, root: tk.Tk, project_root: Path):
        self.root = root
        self.project_root = project_root
        self.logger = EventLogger(project_root)
        self.engine = None
        self.worker = None
        self.publisher_worker = None
        self.report_worker = None
        self.phase_boxes = {}
        self.audit_window = None

        root.title("Catalog Automation Agent")
        root.geometry("1380x700")
        root.minsize(1040, 580)

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Start", command=self.start).pack(side="left", padx=4)
        ttk.Button(top, text="Pause", command=self.pause).pack(side="left", padx=4)
        ttk.Button(top, text="Resume", command=self.resume).pack(side="left", padx=4)
        ttk.Button(top, text="Stop", command=self.stop).pack(side="left", padx=4)
        self.audit_button = ttk.Button(top, text="Audit", command=self.open_audit)
        self.audit_button.pack(side="left", padx=(16, 4))
        self.publish_button = ttk.Button(top, text="Publish", command=self.publish)
        self.publish_button.pack(side="left", padx=4)
        self.report_button = ttk.Button(top, text="Report", command=self.report)
        self.report_button.pack(side="left", padx=4)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=18)

        self._ui_state_path = self.project_root / "runtime_state" / "ui_state.json"
        self._ui_state_path.parent.mkdir(parents=True, exist_ok=True)
        saved_mode = "Default"
        try:
            import json
            st = json.loads(self._ui_state_path.read_text(encoding="utf-8")) if self._ui_state_path.exists() else {}
            saved_mode = "Manual" if str(st.get("mode", "default")).lower() == "manual" else "Default"
        except Exception:
            pass
        self._category_by_display = {v["display_name"]: k for k, v in active_categories().items()}
        self._last_confirmed_category = ""
        self.mode_var = tk.StringVar(value=saved_mode)
        self.category_var = tk.StringVar(value="")
        controls = ttk.Frame(top)
        controls.pack(side="right")
        ttk.Label(controls, text="Category:").pack(side="left", padx=(8,4))
        self.category_combo = ttk.Combobox(controls, textvariable=self.category_var, state="readonly", width=26, values=list(self._category_by_display))
        self.category_combo.pack(side="left", padx=(0,4))
        self.category_combo.bind("<<ComboboxSelected>>", self._confirm_category_selection)
        self.edit_category_button = ttk.Button(controls, text="Edit Category", command=self._edit_category_dialog)
        self.edit_category_button.pack(side="left", padx=(0,10))
        ttk.Label(controls, text="Mode:").pack(side="left", padx=(4,4))
        self.mode_combo = ttk.Combobox(controls, textvariable=self.mode_var, state="readonly", width=9, values=["Default", "Manual"])
        self.mode_combo.pack(side="left")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_ui_state())

        panes = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for phase, title in (("P1", "Image Processing"), ("P2", "Datasheet Resolution"), ("P3", "Content Generation")):
            frame = ttk.Labelframe(panes, text=title, padding=6)
            box = ScrolledText(frame, wrap="none", font=("Consolas", 9), state="disabled")
            box.pack(fill="both", expand=True)
            box.tag_configure("OK", foreground="#16803a")
            box.tag_configure("WARN", foreground="#b26a00")
            box.tag_configure("ERROR", foreground="#b42318")
            box.tag_configure("INFO", foreground="#175cd3")
            box.tag_configure("SKIP", foreground="#667085")
            self.phase_boxes[phase] = box
            panes.add(frame, weight=1)



        self._sync_action_buttons()
        self.root.after(100, self.poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _refresh_category_options(self):
        self._category_by_display = {v['display_name']: key for key, v in active_categories().items()}
        self.category_combo.configure(values=list(self._category_by_display))
        if self.category_var.get() not in self._category_by_display:
            self.category_var.set('')
            self._last_confirmed_category = ''

    def _confirm_category_selection(self, _event=None):
        name = self.category_var.get().strip()
        if not name:
            return
        if messagebox.askyesno('Confirm Category', f'Use category {name} for the next batch?', parent=self.root):
            self._last_confirmed_category = name
        else:
            self.category_var.set(self._last_confirmed_category)

    def _edit_category_dialog(self):
        if self._any_processing() or self._audit_open():
            messagebox.showwarning('Category', 'Stop all work and close Audit before editing categories.', parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title('Edit Category')
        win.geometry('650x560')
        win.transient(self.root)
        win.grab_set()
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Add Category (local software only; WordPress terms must already exist)').pack(anchor='w', pady=4)
        parents = sorted({rec['wordpress']['parent'] for rec in load_registry()['categories'].values()})
        fields = [
            ('Display name (فارسی / English)', 'display_name'),
            ('WordPress category parent', 'parent'),
            ('WordPress existing child name', 'wordpress_child'),
            ('Product title prefix', 'title_prefix'),
            ('SEO density phrase', 'density_phrase'),
            ('Internal category URL', 'category_url'),
            ('WordPress child term ID (optional)', 'wordpress_term_id'),
        ]
        inputs = {}
        for label, key in fields:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label, width=33).pack(side='left')
            var = tk.StringVar(value=parents[0] if key == 'parent' and parents else '')
            if key == 'parent':
                control = ttk.Combobox(row, textvariable=var, state='readonly', values=parents)
            else:
                control = ttk.Entry(row, textvariable=var)
            control.pack(side='left', fill='x', expand=True)
            inputs[key] = var

        def confirm_add():
            values = {key: variable.get().strip() for key, variable in inputs.items()}
            if not messagebox.askyesno('Confirm', f'Add {values["display_name"]!r} to software categories?', parent=win):
                return
            try:
                key = add_category(**values)
                self._refresh_category_options()
                update_delete_options()
                messagebox.showinfo('Category', f'Added {key}. WordPress taxonomy was NOT modified.', parent=win)
            except CategoryAlreadyExists:
                messagebox.showerror('Category', 'Category already exists', parent=win)
            except Exception as exc:
                messagebox.showerror('Category', f'{type(exc).__name__}: {exc}', parent=win)

        ttk.Button(frame, text='Confirm Add', command=confirm_add).pack(anchor='e', pady=8)
        ttk.Separator(frame).pack(fill='x', pady=12)
        ttk.Label(frame, text='Remove custom category from software only').pack(anchor='w')
        selected = tk.StringVar()
        to_remove = ttk.Combobox(frame, textvariable=selected, state='readonly')
        to_remove.pack(fill='x', pady=5)

        def update_delete_options():
            data = {v['display_name']: k for k,v in active_categories().items() if v.get('custom')}
            to_remove.configure(values=list(data))
            if selected.get() not in data:
                selected.set('')
            return data

        def confirm_delete():
            options = update_delete_options()
            display = selected.get().strip()
            if display not in options:
                messagebox.showerror('Category', 'Select an added custom category', parent=win)
                return
            if not messagebox.askyesno('Confirm Delete', f'Remove {display!r} from SOFTWARE only? Existing WordPress categories and products remain unchanged.', parent=win):
                return
            try:
                remove_category(options[display])
                self._refresh_category_options()
                update_delete_options()
                messagebox.showinfo('Category', 'Removed from software; WordPress unchanged.', parent=win)
            except Exception as exc:
                messagebox.showerror('Category', str(exc), parent=win)

        update_delete_options()
        ttk.Button(frame, text='Confirm Delete', command=confirm_delete).pack(anchor='e', pady=7)

    def _save_ui_state(self):
        import json
        mode = self.mode_var.get().strip().lower() or "default"
        self._ui_state_path.write_text(json.dumps({"mode": mode}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _pipeline_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive()) or bool(getattr(self.engine, "running", False))

    def _publisher_running(self) -> bool:
        return bool(self.publisher_worker and self.publisher_worker.is_alive())

    def _report_running(self) -> bool:
        return bool(self.report_worker and self.report_worker.is_alive())

    def _audit_open(self) -> bool:
        return bool(self.audit_window and self.audit_window.winfo_exists())

    def _any_processing(self) -> bool:
        return self._pipeline_running() or self._publisher_running() or self._report_running()

    def _sync_action_buttons(self):
        processing = self._any_processing()
        audit_open = self._audit_open()
        self.audit_button.configure(state="disabled" if processing else "normal")
        # Frozen V3 rule: Publish is enabled only when no pipeline/publisher/report
        # process is active AND Admin Audit is not open.
        idle_for_release = not processing and not audit_open
        self.publish_button.configure(state="normal" if idle_for_release else "disabled")
        self.report_button.configure(state="normal" if idle_for_release else "disabled")
        self.edit_category_button.configure(state="normal" if idle_for_release else "disabled")

    def _append(self, phase: str, line: str, level: str):
        box = self.phase_boxes.get(phase)
        if not box:
            return
        box.configure(state="normal")
        box.insert("end", line + "\n", level)
        box.see("end")
        if int(box.index("end-1c").split(".")[0]) > 3000:
            box.delete("1.0", "500.0")
        box.configure(state="disabled")

    def poll_events(self):
        while True:
            try:
                event = self.logger.events.get_nowait()
            except Exception:
                break
            phase = event.get("phase")
            if phase in self.phase_boxes:
                self._append(phase, event["line"], event.get("level", "INFO"))
            else:
                if event.get("level") in {"WARN", "ERROR", "OK"} or event.get("stage") in {"PREFLIGHT", "DONE", "STOPPED"}:
                    for p in self.phase_boxes:
                        self._append(p, event["line"], event.get("level", "INFO"))
            if event.get("stage") in {"PAUSED_NETWORK", "API_AUTH_INVALID", "API_CREDIT_EXHAUSTED", "STOPPED", "DONE", "PREFLIGHT"}:
                self.status.set(event["message"])
        self._sync_action_buttons()
        self.root.after(100, self.poll_events)

    def start(self):
        if self._any_processing():
            self.status.set("Another process is already running")
            return
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.destroy()
            self.audit_window = None
        category_display = self.category_var.get().strip()
        category_key = self._category_by_display.get(category_display)
        if not category_key:
            messagebox.showerror("Category", "category not seleccted!", parent=self.root)
            return
        mode = self.mode_var.get().strip().lower() or "default"
        # Manual Mode can resume unresolved metadata with zero new input images.
        # The engine scans checkpoints before it starts Phase 1.
        if not messagebox.askyesno('Confirm Category for Batch',
                                   f'Apply {category_display!r} to the complete {mode!r} batch?\n'
                                   'The selected category controls product title, SEO and WordPress mapping.',
                                   parent=self.root):
            return
        self._save_ui_state()
        self.engine = IntegratedOrchestrator(self.project_root, self.logger, input_mode=mode, category_key=category_key)
        # Category must be chosen again before every future Start.
        self.category_var.set("")
        self._last_confirmed_category = ""
        self.status.set("Starting preflight...")
        self.worker = threading.Thread(target=self._run, name="orchestrator-main", daemon=True)
        self.worker.start()
        self._sync_action_buttons()

    def _run(self):
        rc = self.engine.run()
        def finished():
            self.status.set("Completed" if rc == 0 else "Stopped / needs attention")
            self._sync_action_buttons()
        self.root.after(0, finished)

    def pause(self):
        if self.engine: self.engine.pause()
        self.status.set("Pause requested")

    def resume(self):
        if self.engine: self.engine.resume()
        self.status.set("Resume requested")

    def stop(self):
        if self.engine: self.engine.stop()
        self.status.set("Stop requested")

    def open_audit(self):
        if self._any_processing():
            messagebox.showinfo("Audit unavailable", "Wait for all processing to stop before opening Admin Audit.", parent=self.root)
            return
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.lift(); self.audit_window.focus_force(); return
        self.audit_window = AuditWindow(self)

    def publish(self):
        if self._any_processing() or self._audit_open():
            messagebox.showinfo("Publish unavailable", "Publish is available only when the pipeline is idle and Admin Audit is closed.", parent=self.root)
            return
        self.status.set("Phase 4 Publisher starting...")
        self.publisher_worker = threading.Thread(target=self._run_publisher, name="phase4-publisher", daemon=True)
        self.publisher_worker.start()
        self._sync_action_buttons()

    def _run_publisher(self):
        try:
            from run_publisher import main as publisher_main
            rc = publisher_main()
            message = "Publisher completed" if rc == 0 else "Publisher finished with errors / needs review"
        except Exception as exc:
            rc = 3
            message = f"Publisher failed: {type(exc).__name__}: {exc}"
        def finished():
            self.status.set(message)
            self._sync_action_buttons()
        self.root.after(0, finished)

    def report(self):
        if self._any_processing() or self._audit_open():
            messagebox.showinfo("Report unavailable", "Report is generated only from an idle, stable pipeline state.", parent=self.root)
            return
        self.status.set("Generating Excel report...")
        self.report_worker = threading.Thread(target=self._run_report, name="pipeline-report", daemon=True)
        self.report_worker.start()
        self._sync_action_buttons()

    def _run_report(self):
        try:
            path = generate_report(self.project_root)
            message = f"Report created: {path.name}"
            error = None
        except Exception as exc:
            path = None
            message = f"Report failed: {type(exc).__name__}: {exc}"
            error = message
        def finished():
            self.status.set(message)
            self._sync_action_buttons()
            if path:
                messagebox.showinfo("Report", f"Excel report created:\n{path}", parent=self.root)
            elif error:
                messagebox.showerror("Report", error, parent=self.root)
        self.root.after(0, finished)

    def close(self):
        try:
            if self.engine: self.engine.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    project_root = Path(__file__).resolve().parent
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    PipelineUI(root, project_root)
    root.mainloop()


if __name__ == "__main__":
    main()
