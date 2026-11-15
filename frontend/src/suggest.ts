// Search-box autocomplete: object-name suggestions as you type (ARIA combobox pattern).
import { api, type Suggestion } from "./api";

type SuggestResponse = Awaited<ReturnType<typeof api.suggest>>;

const LOCAL_DELAY_MS = 90;    // the built-in index answers in ~10 ms
const LIVE_DELAY_MS = 450;    // SIMBAD takes ~1 s, so only ask once typing pauses

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

/** Bold the parts of ``label`` that the typed words match (word prefixes). */
function highlight(label: string, query: string): string {
  const words = query.toLowerCase().replace(/[^a-z0-9+\-. ]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return esc(label);
  return label.split(/(\s+)/).map((part) => {
    const lw = part.toLowerCase().replace(/'/g, "");
    const w = words.find((q) => lw.startsWith(q));
    if (!w) return esc(part);
    // map the matched length back onto the original (apostrophes were removed)
    let n = 0, i = 0;
    while (i < part.length && n < w.length) { if (part[i] !== "'") n++; i++; }
    return `<b>${esc(part.slice(0, i))}</b>${esc(part.slice(i))}`;
  }).join("");
}

export class Autocomplete {
  private items: Suggestion[] = [];
  private note: string | null = null;
  private active = -1;
  private seq = 0;
  private localTimer: number | undefined;
  private liveTimer: number | undefined;
  private livePending = false;
  private lastQuery = "";

  constructor(private input: HTMLInputElement, private list: HTMLElement,
              private onPick: (s: Suggestion) => void) {
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", list.id);
    list.setAttribute("role", "listbox");
    input.addEventListener("input", () => this.onInput());
    input.addEventListener("keydown", (e) => this.onKey(e));
    input.addEventListener("focus", () => { if (this.items.length || this.note) this.open(); });
    input.addEventListener("blur", () => window.setTimeout(() => this.close(), 120));
    // mousedown (not click) so the choice lands before the input's blur closes the list
    list.addEventListener("mousedown", (e) => {
      const li = (e.target as HTMLElement).closest("li[data-i]") as HTMLElement | null;
      if (!li) return;
      e.preventDefault();
      this.pick(Number(li.dataset.i));
    });
  }

  private onInput() {
    const q = this.input.value.trim();
    this.lastQuery = q;
    window.clearTimeout(this.localTimer);
    window.clearTimeout(this.liveTimer);
    this.livePending = false;
    if (q.length < 2) { this.items = []; this.note = null; this.close(); return; }
    const seq = ++this.seq;
    this.localTimer = window.setTimeout(async () => {
      const r = await this.fetch(q, false);
      if (!r || seq !== this.seq) return;
      this.items = r.items; this.note = r.note; this.active = -1;
      // Designations (contain digits) or few local hits: also ask SIMBAD.
      if (r.items.length < 4 || /\d/.test(q)) {
        this.livePending = true;
        this.liveTimer = window.setTimeout(async () => {
          const lr = await this.fetch(q, true);
          if (seq !== this.seq) return;
          this.livePending = false;
          if (lr) {
            const seen = new Set(this.items.map((i) => i.main_id));
            this.items = [...this.items, ...lr.items.filter((i) => !seen.has(i.main_id))].slice(0, 10);
          }
          this.render();
        }, LIVE_DELAY_MS);
      }
      this.render();
    }, LOCAL_DELAY_MS);
  }

  private async fetch(q: string, live: boolean): Promise<SuggestResponse | null> {
    return api.suggest(q, live).catch(() => null);
  }

  private onKey(e: KeyboardEvent) {
    const open = this.input.getAttribute("aria-expanded") === "true";
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!this.items.length) return;
      e.preventDefault();
      if (!open) this.open();
      const n = this.items.length;
      this.active = e.key === "ArrowDown" ? (this.active + 1) % n : (this.active - 1 + n) % n;
      this.render();
    } else if (e.key === "Enter" && open && this.active >= 0) {
      e.preventDefault();  // choose the highlighted suggestion instead of submitting text
      this.pick(this.active);
    } else if (e.key === "Escape") {
      this.close();
    }
  }

  private pick(i: number) {
    const s = this.items[i];
    if (!s) return;
    this.input.value = s.label;
    this.close();
    this.onPick(s);
  }

  private open() {
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
  }

  close() {
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.active = -1;
  }

  private render() {
    if (this.input.value.trim() !== this.lastQuery) return;
    const q = this.lastQuery;
    const rows = this.items.map((s, i) => {
      const id = `${this.list.id}-opt-${i}`;
      const sel = i === this.active;
      const src = s.source === "simbad" ? `<span class="sg-src">SIMBAD</span>` : "";
      return `<li id="${id}" role="option" data-i="${i}" aria-selected="${sel}" class="${sel ? "active" : ""}">
        <span class="sg-name">${highlight(s.label, q)}</span>
        <span class="sg-type">${esc(s.type || "")}${src}</span></li>`;
    });
    if (this.livePending) rows.push(`<li class="sg-info" aria-disabled="true">Searching SIMBAD…</li>`);
    if (this.note) rows.push(`<li class="sg-info sg-note" aria-disabled="true">${esc(this.note)}</li>`);
    if (!rows.length) rows.push(`<li class="sg-info" aria-disabled="true">No matching names. Press Enter to ask the name resolver anyway.</li>`);
    this.list.innerHTML = rows.join("");
    if (this.active >= 0) {
      this.input.setAttribute("aria-activedescendant", `${this.list.id}-opt-${this.active}`);
      this.list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
    } else {
      this.input.removeAttribute("aria-activedescendant");
    }
    if (document.activeElement === this.input) this.open();
  }
}
