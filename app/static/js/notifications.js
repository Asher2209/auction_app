// Signed-in pages: one shared Socket.IO connection that delivers new notifications live
// (bell badge + toast). Other scripts reuse it as window.chainbidSocket.
// All text is written with textContent; links are only followed if they are in-site paths.
(function () {
  if (typeof io !== "function") return;
  const socket = io();
  window.chainbidSocket = socket;

  const badge = document.getElementById("notif-badge");

  function bump() {
    if (!badge) return;
    badge.textContent = String((parseInt(badge.textContent, 10) || 0) + 1);
    badge.classList.remove("d-none");
  }

  function toast(n) {
    let box = document.getElementById("toast-box");
    if (!box) {
      box = document.createElement("div");
      box.id = "toast-box";
      box.className = "toast-container position-fixed bottom-0 end-0 p-3";
      document.body.appendChild(box);
    }
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    const head = document.createElement("div");
    head.className = "toast-header";
    const strong = document.createElement("strong");
    strong.className = "me-auto";
    strong.textContent = n.title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close";
    close.setAttribute("aria-label", "Close");
    close.setAttribute("data-bs-dismiss", "toast");
    head.append(strong, close);
    const body = document.createElement("div");
    body.className = "toast-body";
    body.textContent = n.message + " ";
    if (typeof n.url === "string" && n.url.startsWith("/") && !n.url.startsWith("//")) {
      const a = document.createElement("a");
      a.href = n.url;
      a.textContent = "View";
      body.appendChild(a);
    }
    el.append(head, body);
    box.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 8000 });
    el.addEventListener("hidden.bs.toast", () => el.remove());
    t.show();
  }

  socket.on("notification", (n) => {
    bump();
    toast(n);
  });
})();
