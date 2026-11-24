/**
 * Bonbon card for Home Assistant.
 *
 * Ships inside the integration and is registered automatically as a frontend
 * resource, so there is nothing to install separately.
 *
 *   type: custom:bonbon-card
 *   entry_id: <optional, shows one config entry when several are set up>
 *   entity: <optional, any entity that carries the bonbon attribute>
 *
 * The card reads the `bonbon` attribute of the number sensor, which holds the
 * whole payload (msisdn, balance, validity, packages) - one attribute, one
 * round trip, no per-field entity juggling.
 */

const CARD = "bonbon-card";
const EDITOR = "bonbon-card-editor";

const ACCENTS = {
  data: "#8b5cf6",
  minutes: "#22d3ee",
  sms: "#fbbf24",
};

const reducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]
  );

const fmtNumber = (value, locale, digits = 2) =>
  new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(value);

const fmtMoney = (value, currency, locale) => {
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: currency || "EUR",
    }).format(value);
  } catch {
    return `${fmtNumber(value, locale)} ${currency || "EUR"}`;
  }
};

const fmtDate = (iso, locale) => {
  if (!iso) return "—";
  const date = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
};

const fmtPhone = (msisdn) => {
  const digits = (msisdn || "").replace(/[^\d]/g, "");
  if (digits.startsWith("385") && digits.length >= 11) {
    const rest = digits.slice(3);
    return `+385 ${rest.slice(0, 2)} ${rest.slice(2, 5)} ${rest.slice(5, 9)}`.trim();
  }
  return msisdn || "—";
};

const unitLabel = (unit) => {
  if (!unit) return "";
  const key = unit.toUpperCase();
  if (key === "GB" || key === "MB") return unit;
  if (key === "MIN") return "min";
  return unit;
};

const kindOf = (pkg) => {
  const unit = (pkg.unit || "").toUpperCase();
  if (unit === "GB" || unit === "MB") return "data";
  if (unit.startsWith("MIN")) return "minutes";
  if (unit === "SMS") return "sms";
  return "data";
};

const timeAgo = (timestamp, locale) => {
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (seconds < 90) return rtf.format(-seconds, "second");
  if (seconds < 5400) return rtf.format(-Math.round(seconds / 60), "minute");
  if (seconds < 129600) return rtf.format(-Math.round(seconds / 3600), "hour");
  return rtf.format(-Math.round(seconds / 86400), "day");
};

class BonbonCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._root = document.createElement("div");
    this._root.className = "root";
    this.shadowRoot.append(this._root);
    this._config = {};
    this._selected = 0;
    this._signature = "";
    this._refreshAt = 0;
  }

  static getStubConfig(hass) {
    const first = Object.values(hass?.states || {}).find(
      (state) => state.attributes?.bonbon
    );
    return first
      ? { type: `custom:${CARD}`, entry_id: first.attributes.bonbon_entry_id }
      : { type: `custom:${CARD}` };
  }

  static getConfigElement() {
    return document.createElement(EDITOR);
  }

  setConfig(config) {
    this._config = { ...config };
    this._signature = "";
    if (this._hass) this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 6, rows: "auto", min_columns: 4 };
  }

  /* ---------------------------------------------------------------- data */

  _collect() {
    const states = this._hass?.states || {};
    const wanted = this._config.entry_id;
    const explicit = this._config.entity;
    return Object.values(states)
      .filter((state) => state.attributes?.bonbon)
      .filter((state) => !wanted || state.attributes.bonbon_entry_id === wanted)
      .filter((state) => !explicit || state.entity_id === explicit)
      .map((state) => ({
        entity_id: state.entity_id,
        state: state.state,
        last_updated: state.last_updated,
        data: state.attributes.bonbon,
      }))
      .sort((a, b) => String(a.data.msisdn).localeCompare(String(b.data.msisdn)));
  }

  _signatureOf(sources) {
    return sources
      .map((s) => `${s.entity_id}:${s.state}:${s.last_updated}`)
      .join("|");
  }

  _update(force = false) {
    const sources = this._collect();
    const signature = this._signatureOf(sources);
    if (!force && signature === this._signature) {
      this._tickFooter();
      return;
    }
    this._signature = signature;
    this._entries = sources;
    if (this._selected >= sources.length) this._selected = 0;
    this._render();
  }

  /* -------------------------------------------------------------- render */

  _render() {
    const locale = this._hass?.locale?.language || navigator.language || "hr";
    const sources = this._entries || [];
    if (!sources.length) {
      this._root.innerHTML = this._shell(this._empty(locale), locale);
      this._wire();
      return;
    }
    const active = sources[this._selected] || sources[0];
    this._root.innerHTML = this._shell(
      `${sources.length > 1 ? this._pills(sources, locale) : ""}
       ${this._body(active, locale)}`,
      locale,
      active,
      sources.length > 1
    );
    this._wire();
    requestAnimationFrame(() => this._animate());
  }

  _shell(inner, locale, active, multi = false) {
    const label = active?.data?.label;
    return `
      <style>${STYLES}</style>
      <div class="card">
        <div class="glow"></div>
        <header class="head">
          <div class="brand">
            <span class="mark"></span>
            <span class="word">bonbon</span>
            <span class="sub">${esc(
              this._config.title || (multi ? "Moj bonbon" : label || "Moj bonbon")
            )}</span>
          </div>
          <button class="icon-btn refresh" type="button" title="${
            locale?.startsWith("hr") ? "Osvježi" : "Refresh"
          }" aria-label="${locale?.startsWith("hr") ? "Osvježi" : "Refresh"}">
            <ha-icon icon="mdi:refresh"></ha-icon>
          </button>
        </header>
        ${inner}
        <footer class="foot">
          <span class="stamp"><i class="pulse"></i><span class="stamp-text">${
            active ? this._stampText(active, locale) : ""
          }</span></span>
          <a class="portal" href="https://www.bonbon.hr" target="_blank" rel="noreferrer">bonbon.hr</a>
        </footer>
      </div>`;
  }

  _empty(locale) {
    const hr = locale?.startsWith("hr");
    return `
      <div class="empty">
        <ha-icon icon="mdi:sim-alert"></ha-icon>
        <p>${hr ? "Nema bonbon brojeva." : "No Bonbon numbers found."}</p>
        <small>${
          hr
            ? "Provjeri da je integracija dodana i da je barem jedan broj vidljiv."
            : "Check that the integration is set up and at least one number is visible."
        }</small>
      </div>`;
  }

  _pills(sources, locale) {
    return `<div class="pills" role="tablist">${sources
      .map(
        (source, index) => `
        <button class="pill ${index === this._selected ? "on" : ""}" type="button"
                role="tab" aria-selected="${index === this._selected}"
                data-index="${index}">
          <span class="pill-num">${esc(fmtPhone(source.data.msisdn))}</span>
          ${
            source.data.label
              ? `<span class="pill-label">${esc(source.data.label)}</span>`
              : ""
          }
        </button>`
      )
      .join("")}</div>`;
  }

  _body(source, locale) {
    const data = source.data;
    const hr = locale?.startsWith("hr");
    const packages = data.packages || [];
    const days = this._daysLeft(data.valid_until);
    const hasBalance = data.balance !== null && data.balance !== undefined;
    const count = packages.length;
    return `
      <section class="hero">
        <div class="hero-left">
          <div class="msisdn">${esc(fmtPhone(data.msisdn))}</div>
          <div class="overline">${hr ? "Stanje računa" : "Balance"}</div>
          ${
            hasBalance
              ? `<div class="balance count" data-value="${data.balance}"
                     data-currency="${data.currency || "EUR"}">${fmtMoney(
                       data.balance,
                       data.currency,
                       locale
                     )}</div>`
              : `<div class="balance empty">—</div>`
          }
          <div class="hero-meta">
            ${
              data.valid_until
                ? `<span class="chip"><ha-icon icon="mdi:calendar-check"></ha-icon>${
                    hr ? "do" : "until"
                  } ${fmtDate(data.valid_until, locale)}</span>`
                : ""
            }
            ${
              data.label
                ? `<span class="chip"><ha-icon icon="mdi:account"></ha-icon>${esc(data.label)}</span>`
                : ""
            }
            ${
              !hasBalance && data.spending !== null && data.spending !== undefined
                ? `<span class="chip"><ha-icon icon="mdi:cash-minus"></ha-icon>${hr ? "potrošeno" : "spent"} ${fmtMoney(data.spending, data.currency, locale)}</span>`
                : ""
            }
          </div>
        </div>
        ${this._ring(days, locale)}
      </section>

      ${
        data.portal_message
          ? `<div class="notice"><ha-icon icon="mdi:information-outline"></ha-icon><span>${esc(
              data.portal_message
            )}</span></div>`
          : ""
      }

      <section class="packages">
        <div class="section-head">
          <span>${hr ? "Aktivni paketi" : "Active packages"}</span>
          <span class="badge">${count}</span>
        </div>
        ${
          count
            ? `<ul class="list">${packages
                .map((pkg, index) => this._package(pkg, index, locale))
                .join("")}</ul>`
            : `<div class="none">${
                hr ? "Nema aktivnih paketa." : "No active packages."
              }</div>`
        }
      </section>`;
  }

  _package(pkg, index, locale) {
    const kind = kindOf(pkg);
    const accent = ACCENTS[kind] || ACCENTS.data;
    const hasQuota = typeof pkg.remaining === "number" && pkg.total;
    const pct = hasQuota
      ? Math.max(0, Math.min(100, (pkg.remaining / pkg.total) * 100))
      : 0;
    const value = hasQuota
      ? `${fmtNumber(pkg.remaining, locale)}<span class="muted"> / ${fmtNumber(
          pkg.total,
          locale
        )} ${unitLabel(pkg.unit)}</span>`
      : pkg.remaining !== null && pkg.remaining !== undefined
        ? `${fmtNumber(pkg.remaining, locale)} ${unitLabel(pkg.unit)}`
        : "—";
    const meta = [
      pkg.expires
        ? `${locale?.startsWith("hr") ? "do" : "until"} ${fmtDate(pkg.expires, locale)}`
        : "",
      pkg.auto_renew
        ? locale?.startsWith("hr")
          ? "auto-obnova"
          : "auto-renew"
        : "",
    ].filter(Boolean);

    return `
      <li class="pkg" style="--accent:${accent}; --i:${index}">
        <div class="pkg-top">
          <span class="pkg-name">${esc(pkg.name || "Paket")}</span>
          <span class="pkg-value">${value}</span>
        </div>
        ${
          hasQuota
            ? `<div class="bar"><i data-w="${pct}"></i></div>`
            : `<div class="bar thin"><i data-w="100" style="opacity:.25"></i></div>`
        }
        ${
          meta.length
            ? `<div class="pkg-meta">${meta.join(" · ")}</div>`
            : ""
        }
      </li>`;
  }

  _ring(days, locale) {
    const span = 30;
    const left = days === null ? 0 : Math.max(0, Math.min(span, days));
    const ratio = days === null ? 0 : Math.max(left / span, 0.06);
    const circumference = 2 * Math.PI * 18;
    const dash = `${(circumference * ratio).toFixed(1)} ${circumference.toFixed(1)}`;
    const tone = days !== null && days <= 3 ? "#f87171" : "url(#ringGrad)";
    return `
      <div class="ring ${days !== null && days <= 3 ? "low" : ""}" title="${
        locale?.startsWith("hr") ? "Valjanost" : "Validity"
      }">
        <svg viewBox="0 0 44 44" role="img" aria-label="${
          days === null ? "—" : `${days}`
        }">
          <defs>
            <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#a78bfa"/>
              <stop offset="100%" stop-color="#f472b6"/>
            </linearGradient>
          </defs>
          <circle class="track" cx="22" cy="22" r="18"></circle>
          <circle class="arc" cx="22" cy="22" r="18"
                  stroke="${tone}" stroke-dasharray="${dash}"
                  ${days === null ? 'opacity="0"' : ""}
                  transform="rotate(-90 22 22)"></circle>
        </svg>
        <div class="ring-label">
          <strong class="count" data-value="${days ?? ""}">${days === null ? "—" : days}</strong>
          <span>${locale?.startsWith("hr") ? "dana" : "days"}</span>
        </div>
      </div>`;
  }

  _stampText(source, locale) {
    const stamp = Number(source.last_updated) * 1000;
    const hr = locale?.startsWith("hr");
    if (!stamp) return "";
    return `${hr ? "Osvježeno" : "Updated"} ${timeAgo(stamp, locale)}`;
  }

  _daysLeft(iso) {
    if (!iso) return null;
    const target = new Date(`${iso}T23:59:59`);
    if (Number.isNaN(target.getTime())) return null;
    return Math.ceil((target - Date.now()) / 86400000);
  }

  /* --------------------------------------------------------------- wiring */

  _wire() {
    const root = this._root;
    root.querySelector(".refresh")?.addEventListener("click", (event) => {
      event.preventDefault();
      this._refresh();
    });
    root.querySelectorAll(".pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        this._selected = Number(pill.dataset.index) || 0;
        this._render();
      });
    });
  }

  _tickFooter() {
    const node = this._root.querySelector(".stamp-text");
    const source = (this._entries || [])[this._selected];
    if (!node || !source) return;
    const locale = this._hass?.locale?.language || navigator.language || "hr";
    node.textContent = this._stampText(source, locale);
  }

  async _refresh() {
    if (!this._hass || Date.now() - this._refreshAt < 5000) return;
    this._refreshAt = Date.now();
    const button = this._root.querySelector(".refresh");
    button?.classList.add("spin");
    const sources = this._entries || [];
    try {
      await Promise.all(
        sources.map((source) =>
          this._hass.callService("homeassistant", "update_entity", {
            entity_id: source.entity_id,
          })
        )
      );
    } catch {
      /* the coordinator reports the real error; the card only shows state */
    } finally {
      setTimeout(() => button?.classList.remove("spin"), 600);
    }
  }

  /* ------------------------------------------------------------ animation */

  _animate() {
    this._root.querySelectorAll(".bar > i").forEach((bar) => {
      const width = Number(bar.dataset.w) || 0;
      if (reducedMotion()) {
        bar.style.width = `${width}%`;
        return;
      }
      bar.style.width = "0%";
      requestAnimationFrame(() => requestAnimationFrame(() => {
        bar.style.width = `${width}%`;
      }));
    });

    if (reducedMotion()) return;
    this._root.querySelectorAll(".count").forEach((node) => {
      const raw = node.dataset.value;
      const target = Number(raw);
      if (!raw || Number.isNaN(target)) return;
      const currency = node.dataset.currency;
      const locale = this._hass?.locale?.language || navigator.language || "hr";
      const isMoney = Boolean(currency) && node.classList.contains("balance");
      const start = performance.now();
      const duration = 700;
      const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        const value = target * eased;
        node.textContent = isMoney
          ? fmtMoney(value, currency, locale)
          : fmtNumber(Math.round(value), locale, 0);
        if (progress < 1) requestAnimationFrame(step);
        else
          node.textContent = isMoney
            ? fmtMoney(target, currency, locale)
            : fmtNumber(Math.round(target), locale, 0);
      };
      requestAnimationFrame(step);
    });
  }
}

class BonbonCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._config) return;
    const signature = JSON.stringify(this._config);
    if (this._signature === signature && this._rendered) return;
    this._signature = signature;
    this._rendered = true;
    const entries = new Map();
    for (const state of Object.values(this._hass?.states || {})) {
      const attr = state.attributes?.bonbon;
      if (attr) entries.set(state.attributes.bonbon_entry_id, attr);
    }
    const value = this._config.entry_id || "";
    this.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;padding:8px 0">
        <label style="font-size:14px">
          bonbon račun
          <select style="display:block;width:100%;margin-top:6px;padding:8px;border-radius:8px">
            <option value="">Svi računi</option>
            ${[...entries.entries()]
              .map(
                ([id, attr]) =>
                  `<option value="${id}" ${id === value ? "selected" : ""}>${
                    attr.label || fmtPhone(attr.msisdn)
                  }</option>`
              )
              .join("")}
          </select>
        </label>
      </div>`;
    this.querySelector("select")?.addEventListener("change", (event) => {
      const entry_id = event.target.value;
      const config = { ...this._config, entry_id };
      if (!entry_id) delete config.entry_id;
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config },
          bubbles: true,
          composed: true,
        })
      );
    });
  }
}

const STYLES = `
  :host {
    --bonbon-radius: 22px;
    --bonbon-text: #f8f5ff;
    --bonbon-muted: rgba(248, 245, 255, 0.62);
    --bonbon-line: rgba(255, 255, 255, 0.09);
    display: block;
    font-family: var(--ha-font-family-body, "Inter", "Roboto", system-ui, sans-serif);
    color: var(--bonbon-text);
    container-type: inline-size;
  }
  .root { display: block; }
  .card {
    position: relative;
    overflow: hidden;
    border-radius: var(--bonbon-radius);
    padding: 18px 18px 14px;
    background:
      radial-gradient(120% 90% at 0% 0%, rgba(139, 92, 246, 0.35), transparent 55%),
      radial-gradient(120% 80% at 100% 0%, rgba(244, 114, 182, 0.25), transparent 50%),
      linear-gradient(165deg, #1a1029 0%, #120b1d 55%, #170d22 100%);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.08) inset,
      0 18px 38px -18px rgba(9, 5, 20, 0.9),
      0 2px 10px rgba(0, 0, 0, 0.35);
    border: 1px solid var(--bonbon-line);
    transition: transform 220ms ease, box-shadow 220ms ease;
    animation: rise 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
  }
  .card:hover {
    transform: translateY(-2px);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.1) inset,
      0 26px 48px -20px rgba(9, 5, 20, 0.95),
      0 2px 10px rgba(0, 0, 0, 0.4);
  }
  .card::after {
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background: linear-gradient(118deg, rgba(255, 255, 255, 0.07) 0%, transparent 38%);
  }
  .glow {
    position: absolute;
    inset: -40% -20% auto auto;
    width: 260px; height: 260px;
    background: radial-gradient(circle, rgba(167, 139, 250, 0.4), transparent 65%);
    filter: blur(30px);
    pointer-events: none;
    animation: drift 14s ease-in-out infinite alternate;
  }
  .head {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; margin-bottom: 14px; position: relative; z-index: 1;
  }
  .brand { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .mark {
    width: 9px; height: 9px; border-radius: 50%;
    background: linear-gradient(140deg, #f472b6, #a78bfa);
    box-shadow: 0 0 0 4px rgba(167, 139, 250, 0.14), 0 0 14px rgba(244, 114, 182, 0.7);
  }
  .word {
    font-weight: 800; letter-spacing: -0.03em; font-size: 17px;
    background: linear-gradient(100deg, #ffffff, #f9a8d4 60%, #c4b5fd);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .sub {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.14em;
    color: var(--bonbon-muted); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; padding-left: 6px; border-left: 1px solid var(--bonbon-line);
  }
  .icon-btn {
    appearance: none; border: 1px solid var(--bonbon-line);
    background: rgba(255, 255, 255, 0.04); color: var(--bonbon-muted);
    width: 32px; height: 32px; border-radius: 11px; cursor: pointer;
    display: grid; place-items: center; transition: all 180ms ease;
  }
  .icon-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.1); }
  .icon-btn:focus-visible, .pill:focus-visible { outline: 2px solid #a78bfa; outline-offset: 2px; }
  .icon-btn ha-icon { --mdc-icon-size: 18px; }
  .icon-btn.spin ha-icon { animation: spin 700ms linear infinite; }

  .pills {
    display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 10px;
    scrollbar-width: none;
  }
  .pills::-webkit-scrollbar { display: none; }
  .pill {
    appearance: none; cursor: pointer; white-space: nowrap;
    border: 1px solid var(--bonbon-line); background: rgba(255, 255, 255, 0.04);
    color: var(--bonbon-muted); border-radius: 999px; padding: 6px 12px;
    font: inherit; font-size: 12px; font-weight: 600;
    display: flex; flex-direction: column; align-items: flex-start; gap: 1px;
    transition: all 180ms ease;
  }
  .pill:hover { color: #fff; border-color: rgba(255, 255, 255, 0.2); }
  .pill.on {
    color: #fff; border-color: transparent;
    background: linear-gradient(120deg, rgba(167, 139, 250, 0.9), rgba(244, 114, 182, 0.85));
    box-shadow: 0 6px 18px -8px rgba(244, 114, 182, 0.9);
  }
  .pill-label { font-size: 10px; font-weight: 500; opacity: 0.72; }

  .hero {
    position: relative; z-index: 1; display: flex; align-items: center;
    justify-content: space-between; gap: 14px;
  }
  .hero-left { min-width: 0; }
  .msisdn {
    font-size: 12.5px; font-weight: 600; letter-spacing: 0.055em;
    color: var(--bonbon-muted); font-variant-numeric: tabular-nums;
  }
  .overline {
    font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase;
    color: var(--bonbon-muted); font-weight: 600; margin-top: 9px;
  }
  .balance {
    font-size: clamp(30px, 10cqw, 40px); font-weight: 800; letter-spacing: -0.03em;
    line-height: 1.05; margin-top: 1px; font-variant-numeric: tabular-nums;
    background: linear-gradient(100deg, #ffffff 10%, #ede9fe 55%, #f9a8d4 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
    white-space: nowrap;
  }
  .balance.empty {
    background: none; -webkit-text-fill-color: var(--bonbon-muted);
    color: var(--bonbon-muted); font-size: 26px; letter-spacing: 0.1em;
  }
  .hero-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .hero-meta:empty { display: none; }
  .chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 4px 9px;
    border-radius: 999px; border: 1px solid var(--bonbon-line);
    background: rgba(255, 255, 255, 0.045); font-size: 10.5px; font-weight: 600;
    color: var(--bonbon-muted); white-space: nowrap;
  }
  .chip ha-icon { --mdc-icon-size: 13px; color: #c4b5fd; }

  .ring { position: relative; width: 84px; height: 84px; flex: 0 0 84px; }
  .ring svg { width: 100%; height: 100%; display: block; }
  .ring .track { fill: none; stroke: rgba(255, 255, 255, 0.1); stroke-width: 4; }
  .ring .arc {
    fill: none; stroke-width: 4; stroke-linecap: round;
    transition: stroke-dasharray 900ms cubic-bezier(0.22, 1, 0.36, 1);
    filter: drop-shadow(0 0 6px rgba(167, 139, 250, 0.55));
  }
  .ring.low .arc { filter: drop-shadow(0 0 7px rgba(248, 113, 113, 0.65)); }
  .ring-label {
    position: absolute; inset: 0; display: grid; place-content: center;
    text-align: center; line-height: 1;
  }
  .ring-label strong { font-size: 19px; font-weight: 800; letter-spacing: -0.02em; }
  .ring-label span {
    font-size: 8px; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--bonbon-muted); margin-top: 2px;
  }

  .notice {
    display: flex; gap: 7px; align-items: flex-start; margin-top: 12px;
    padding: 8px 10px; border-radius: 12px; position: relative; z-index: 1;
    background: rgba(251, 191, 36, 0.08); border: 1px solid rgba(251, 191, 36, 0.22);
    color: #fcd34d; font-size: 10.5px; line-height: 1.35;
  }
  .notice ha-icon { --mdc-icon-size: 14px; flex: 0 0 14px; margin-top: 1px; }
  .notice span {
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .packages { margin-top: 16px; position: relative; z-index: 1; }
  .section-head {
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--bonbon-muted); font-weight: 700;
  }
  .badge {
    margin-left: auto; font-size: 10px; letter-spacing: 0; padding: 1px 8px;
    border-radius: 999px; background: rgba(167, 139, 250, 0.18);
    color: #ddd6fe; border: 1px solid rgba(167, 139, 250, 0.3);
  }
  .list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
  .pkg {
    border: 1px solid var(--bonbon-line); border-radius: 14px; padding: 10px 12px;
    background: linear-gradient(160deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.015));
    animation: rise 380ms cubic-bezier(0.22, 1, 0.36, 1) both;
    animation-delay: calc(var(--i) * 60ms);
  }
  .pkg-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
  .pkg-name {
    font-size: 13px; font-weight: 650; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }
  .pkg-value { font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .pkg-value .muted { color: var(--bonbon-muted); }
  .bar {
    margin-top: 7px; height: 6px; border-radius: 999px; overflow: hidden;
    background: rgba(255, 255, 255, 0.08);
  }
  .bar.thin { height: 3px; }
  .bar > i {
    display: block; height: 100%; width: 0; border-radius: inherit;
    background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #ffffff));
    box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 55%, transparent);
    transition: width 900ms cubic-bezier(0.22, 1, 0.36, 1);
  }
  .pkg-meta { margin-top: 6px; font-size: 10.5px; color: var(--bonbon-muted); }
  .none {
    border: 1px dashed var(--bonbon-line); border-radius: 14px; padding: 16px;
    text-align: center; font-size: 12px; color: var(--bonbon-muted);
  }

  .foot {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--bonbon-line);
    font-size: 10.5px; color: var(--bonbon-muted);
  }
  .stamp { display: inline-flex; align-items: center; gap: 6px; }
  .pulse {
    width: 5px; height: 5px; border-radius: 50%; background: #34d399;
    box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.18);
  }
  .portal { color: var(--bonbon-muted); text-decoration: none; }
  .portal:hover { color: #fff; }

  .empty {
    display: grid; place-items: center; gap: 6px; padding: 28px 10px;
    text-align: center; color: var(--bonbon-muted);
  }
  .empty ha-icon { --mdc-icon-size: 30px; color: #c4b5fd; }
  .empty p { margin: 0; color: var(--bonbon-text); font-weight: 600; font-size: 14px; }
  .empty small { font-size: 11px; max-width: 32ch; line-height: 1.4; }

  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes drift { from { transform: translate3d(0, 0, 0) scale(1); } to { transform: translate3d(-24px, 18px, 0) scale(1.12); } }

  @container (max-width: 330px) {
    .ring { width: 66px; height: 66px; flex-basis: 66px; }
    .chip { font-size: 10px; padding: 3px 7px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .card, .pkg, .glow, .arc, .bar > i { animation: none !important; transition: none !important; }
  }
`;

if (!customElements.get(CARD)) customElements.define(CARD, BonbonCard);
if (!customElements.get(EDITOR)) customElements.define(EDITOR, BonbonCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Bonbon",
    description:
      "Brojevi, aktivni paketi, stanje računa i valjanost — sve na jednoj kartici.",
    preview: true,
    documentationURL: "https://github.com/ngarafol/mojbonboninfo",
  });
}
