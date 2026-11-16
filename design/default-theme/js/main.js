// Restaurant Remelle — small UI interactions (no dependencies)
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // Mobile nav
  const toggle = $("#navToggle");
  const links = $("#navLinks");
  toggle.addEventListener("click", () => {
    const open = links.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open);
    toggle.innerHTML = open ? '<i class="bi bi-x-lg"></i>' : '<i class="bi bi-list"></i>';
  });
  $$("a", links).forEach((a) =>
    a.addEventListener("click", () => {
      links.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.innerHTML = '<i class="bi bi-list"></i>';
    })
  );

  // Toast + cart counter
  const toast = $("#toast");
  const cartCount = $("#cartCount");
  let count = 0;
  let toastTimer;
  function addToCart(n, label) {
    count += n;
    cartCount.textContent = count;
    toast.textContent = `${label} added to cart`;
    toast.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-show"), 1800);
  }

  $$("[data-add]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const name = btn.closest(".item").querySelector("h4").textContent.trim();
      addToCart(1, name);
      btn.classList.add("is-added");
      btn.innerHTML = '<i class="bi bi-check"></i>';
      setTimeout(() => {
        btn.classList.remove("is-added");
        btn.innerHTML = '<i class="bi bi-plus"></i>';
      }, 1200);
    })
  );

  // Signature dish: extras + quantity → total
  const base = 520;
  const qtyOut = $("[data-stepper] output");
  const totalEl = $("#dishTotal");
  const extras = $$("[data-extra]");
  function updateDish() {
    const extra = extras.filter((e) => e.checked).reduce((s, e) => s + Number(e.dataset.extra), 0);
    const total = (base + extra) * Number(qtyOut.textContent);
    totalEl.textContent = total.toLocaleString("en-IN");
  }
  $$("[data-step]").forEach((b) =>
    b.addEventListener("click", () => {
      const q = Math.max(1, Math.min(20, Number(qtyOut.textContent) + Number(b.dataset.step)));
      qtyOut.textContent = q;
      updateDish();
    })
  );
  extras.forEach((e) => e.addEventListener("change", updateDish));
  $("[data-add-dish]").addEventListener("click", () => addToCart(Number(qtyOut.textContent), "Grilled Salmon"));

  // Favourite
  const fav = $("[data-fav]");
  fav.addEventListener("click", () => {
    const on = fav.classList.toggle("is-on");
    fav.innerHTML = on ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>';
  });

  // Delivery type pills
  const pills = $$(".pill");
  pills.forEach((p) =>
    p.addEventListener("click", () => {
      pills.forEach((x) => {
        x.classList.remove("is-active");
        x.setAttribute("aria-checked", "false");
      });
      p.classList.add("is-active");
      p.setAttribute("aria-checked", "true");
    })
  );
})();
