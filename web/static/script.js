// Small helpers for the admin panel (no dependencies).

// ===== TOAST =====
function showToast(message, kind) {
    var box = document.getElementById("toasts");
    if (!box) {
        box = document.createElement("div");
        box.id = "toasts";
        document.body.appendChild(box);
    }
    var toast = document.createElement("div");
    toast.className = "toast" + (kind === "err" ? " err" : "");
    toast.textContent = message;              // textContent: never interpret as HTML
    box.appendChild(toast);
    setTimeout(function () {
        toast.classList.add("hide");
        setTimeout(function () { toast.remove(); }, 300);
    }, kind === "err" ? 6000 : 3500);
}

// ===== CONFIRM =====
function confirmAction(message) {
    return window.confirm(message);
}

// ===== TABLE FILTER =====
// <input data-filter="my-table"> hides the rows of #my-table that don't contain the text.
function filterTable(input) {
    var table = document.getElementById(input.getAttribute("data-filter"));
    if (!table) return;
    var needle = input.value.trim().toLowerCase();
    var rows = table.querySelectorAll("tr");
    for (var i = 0; i < rows.length; i++) {
        if (rows[i].querySelector("th")) continue;          // keep the header row
        rows[i].style.display =
            !needle || rows[i].textContent.toLowerCase().indexOf(needle) !== -1 ? "" : "none";
    }
}

document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("input[data-filter]")) filterTable(e.target);
});

// <button data-confirm="Sure?"> asks before the form is submitted
document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-confirm]") : null;
    if (el && !confirmAction(el.getAttribute("data-confirm"))) {
        e.preventDefault();
        e.stopPropagation();
    }
});

// Server-side flash messages -> toasts (the banner stays visible if JS is off)
document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll(".flash");
    for (var i = 0; i < flashes.length; i++) {
        showToast(flashes[i].textContent.trim(), flashes[i].classList.contains("err") ? "err" : "ok");
        flashes[i].style.display = "none";
    }
});

// <button data-copy="text"> copies the text (falls back to a prompt where the clipboard API is blocked)
document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-copy]") : null;
    if (!el) return;
    var text = el.getAttribute("data-copy");
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
            function () { showToast("Link copied."); },
            function () { window.prompt("Copy the link:", text); }
        );
    } else {
        window.prompt("Copy the link:", text);
    }
});

// Dashboard numbers refresh every 20 s: <div data-live="/admin/api/stats"> with <p data-stat="users"> inside.
(function () {
    var box = document.querySelector("[data-live]");
    if (!box || !window.fetch) return;
    function refresh() {
        if (document.hidden) return;
        fetch(box.getAttribute("data-live"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                var els = box.querySelectorAll("[data-stat]");
                for (var i = 0; i < els.length; i++) {
                    var v = d[els[i].getAttribute("data-stat")];
                    if (v !== undefined) els[i].textContent = v;      // textContent: never HTML
                }
            })
            .catch(function () {});
    }
    setInterval(refresh, 20000);
})();

