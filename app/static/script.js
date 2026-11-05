const slotList = document.getElementById("slot-list");
const slotStatus = document.getElementById("slot-status");
const bookingSection = document.getElementById("booking-section");
const selectedSlotText = document.getElementById("selected-slot");
const bookingForm = document.getElementById("booking-form");
const confirmBtn = document.getElementById("confirm-btn");
const formError = document.getElementById("form-error");
const confirmation = document.getElementById("confirmation");
const lookupForm = document.getElementById("lookup-form");
const refInput = document.getElementById("ref");
const lookupList = document.getElementById("lookup-list");
const lookupError = document.getElementById("lookup-error");
const mineForm = document.getElementById("mine-form");
const mineEmail = document.getElementById("mine-email");
const myList = document.getElementById("my-list");
const moreBtn = document.getElementById("more-btn");
const mineError = document.getElementById("mine-error");

let selectedSlot = null;
let idempotencyKey = null;
let mineCursor = null;


function formatTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}


function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}


// ---------- Slots ----------

async function loadSlots() {
  slotStatus.textContent = "Loading...";
  try {
    const res = await fetch("/page/slots");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load slots");

    slotList.innerHTML = "";
    if (data.slots.length === 0) {
      slotStatus.textContent = "No appointments are available right now.";
      return;
    }
    slotStatus.textContent = "";

    for (const slot of data.slots) {
      const li = document.createElement("li");

      const info = document.createElement("div");
      info.className = "slot-info";
      info.innerHTML = `<strong>${escapeHtml(slot.provider)}</strong>
        <span>${formatTime(slot.start)} – ${formatTime(slot.end)}</span>`;

      const action = document.createElement("div");
      const badge = document.createElement("span");
      if (slot.available) {
        badge.className = "badge";
        badge.textContent = "Available";
        const btn = document.createElement("button");
        btn.className = "small";
        btn.textContent = "Book appointment";
        btn.onclick = () => selectSlot(slot);
        action.append(badge, " ", btn);
      } else {
        badge.className = "badge booked";
        badge.textContent = "Booked";
        action.append(badge);
      }

      li.append(info, action);
      slotList.append(li);
    }
  } catch (err) {
    slotStatus.textContent = err.message;
  }
}


// ---------- Booking ----------

function selectSlot(slot) {
  selectedSlot = slot;
  idempotencyKey = crypto.randomUUID();
  selectedSlotText.textContent = `Booking: ${slot.provider}, ${formatTime(slot.start)}`;
  formError.textContent = "";
  bookingSection.hidden = false;
  confirmation.hidden = true;
  bookingSection.scrollIntoView({ behavior: "smooth" });
}


bookingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedSlot) return;

  formError.textContent = "";
  confirmBtn.disabled = true;

  const payload = {
    slot_id: selectedSlot.id,
    name: document.getElementById("name").value,
    email: document.getElementById("email").value,
  };

  try {
    const res = await fetch("/page/bookings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Same key on retry, so a repeated click can't create a second booking
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Booking failed");

    showConfirmation(data, selectedSlot);
    bookingForm.reset();
    bookingSection.hidden = true;
    selectedSlot = null;
    idempotencyKey = null;
    loadSlots();
  } catch (err) {
    formError.textContent = err.message;
  } finally {
    confirmBtn.disabled = false;
  }
});


function showConfirmation(booking, slot) {
  confirmation.innerHTML = `
    <h2>Booking confirmed</h2>
    <dl>
      <dt>Reference</dt><dd>${escapeHtml(booking.id)}</dd>
      <dt>Patient</dt><dd>${escapeHtml(booking.name)}</dd>
      <dt>Email</dt><dd>${escapeHtml(booking.email)}</dd>
      <dt>Provider</dt><dd>${escapeHtml(slot.provider)}</dd>
      <dt>When</dt><dd>${formatTime(slot.start)}</dd>
    </dl>
    <p id="cancel-msg" class="error"></p>
    <button id="cancel-btn" class="small" type="button">Cancel this booking</button>`;
  confirmation.hidden = false;

  document.getElementById("cancel-btn").onclick = async () => {
    const btn = document.getElementById("cancel-btn");
    const msg = document.getElementById("cancel-msg");
    btn.disabled = true;
    try {
      await cancelRequest(booking.id);
      confirmation.innerHTML = `
        <h2>Booking cancelled</h2>
        <p>Reference: ${escapeHtml(booking.id)}</p>`;
      loadSlots();
    } catch (err) {
      msg.textContent = err.message;
      btn.disabled = false;
    }
  };
}


// ---------- Shared cancel and rendering ----------

async function cancelRequest(bookingId) {
  const res = await fetch(`/page/bookings/${encodeURIComponent(bookingId)}`, {
    method: "DELETE",
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not cancel the booking");
  return data;
}


function bookingItem(b, onChange) {
  const li = document.createElement("li");

  const info = document.createElement("div");
  info.className = "slot-info";
  info.innerHTML = `<strong>${escapeHtml(b.name)} (${escapeHtml(b.status)})</strong>
    <span>Reference: ${escapeHtml(b.id)}<br>
    Slot: ${escapeHtml(b.slot_id)} · Booked: ${formatTime(b.created_at)}</span>`;
  li.append(info);

  if (b.status === "confirmed") {
    const btn = document.createElement("button");
    btn.className = "small";
    btn.textContent = "Cancel";
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await cancelRequest(b.id);
        loadSlots();
        onChange();
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    };
    li.append(btn);
  }
  return li;
}


// ---------- Look up by reference ----------

async function runLookup(id) {
  lookupError.textContent = "";
  lookupList.innerHTML = "";
  try {
    const res = await fetch(`/page/bookings/${encodeURIComponent(id)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Booking not found");
    lookupList.append(bookingItem(data, () => runLookup(id)));
  } catch (err) {
    lookupError.textContent = err.message;
  }
}

lookupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const id = refInput.value.trim();
  if (!id) {
    lookupError.textContent = "Enter a booking reference.";
    return;
  }
  runLookup(id);
});


// ---------- My bookings (paginated) ----------

async function loadMine(reset) {
  mineError.textContent = "";
  const email = mineEmail.value.trim();
  if (!email) {
    mineError.textContent = "Enter your email address.";
    return;
  }
  if (reset) {
    myList.innerHTML = "";
    mineCursor = null;
  }

  const params = new URLSearchParams({ email, limit: "5" });
  if (mineCursor) params.set("cursor", mineCursor);

  try {
    const res = await fetch(`/page/bookings?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load bookings");

    if (reset && data.bookings.length === 0) {
      myList.textContent = "No bookings found for this email.";
    }
    for (const b of data.bookings) {
      myList.append(bookingItem(b, () => loadMine(true)));
    }
    mineCursor = data.next_cursor;
    moreBtn.hidden = !mineCursor;
  } catch (err) {
    mineError.textContent = err.message;
  }
}

mineForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadMine(true);
});

moreBtn.addEventListener("click", () => loadMine(false));


loadSlots();