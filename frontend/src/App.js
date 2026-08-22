import { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { BrowserRouter } from "react-router-dom";
import {
  CalendarDays, Clock3, HeartPulse, LogOut, Search, ShieldCheck, Stethoscope,
  Users, ArrowRight, Pill, Bell, Plus, Trash2, FileText, X, Timer, CalendarClock,
} from "lucide-react";
import "@/App.css";
import "@/portal.css";

const client = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });
const auth = (t) => ({ headers: { Authorization: `Bearer ${t}` } });

/* --------------------------- entry & authentication --------------------------- */
export default function App() {
  const [session, setSession] = useState(() =>
    JSON.parse(localStorage.getItem("pulsecare_session") || "null"),
  );
  const logout = () => {
    localStorage.removeItem("pulsecare_session");
    setSession(null);
  };
  if (!session) return <AuthScreen onSuccess={(d) => { localStorage.setItem("pulsecare_session", JSON.stringify(d)); setSession(d); }} />;
  return (
    <BrowserRouter>
      <Dashboard session={session} logout={logout} />
    </BrowserRouter>
  );
}

function AuthScreen({ onSuccess }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const r = await client.post(`/auth/${mode}`, form);
      onSuccess(r.data);
    } catch (x) {
      setError(x.response?.data?.detail || "Could not connect. Please try again.");
    }
  };
  return (
    <main className="auth-shell">
      <section className="auth-visual">
        <div className="brand"><HeartPulse size={22} /> PulseCare</div>
        <div className="visual-copy">
          <span className="eyebrow">CARE, ORGANIZED</span>
          <h1>Every visit,<br /><em>thoughtfully</em> connected.</h1>
          <p>A calmer way to manage care, from the first appointment to the follow-up.</p>
        </div>
        <div className="trust-row"><ShieldCheck size={18} /> Private by design <span>•</span> Built for care teams</div>
      </section>
      <section className="auth-panel">
        <div className="auth-form">
          <span className="eyebrow teal">WELCOME BACK</span>
          <h2>{mode === "login" ? "Sign in to PulseCare" : "Create your patient account"}</h2>
          <p className="muted">{mode === "login" ? "Your care dashboard is waiting." : "Start managing your visits in one place."}</p>
          <form onSubmit={submit}>
            {mode === "register" && (
              <label>Full name
                <input data-testid="register-name-input" required value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Alex Morgan" />
              </label>
            )}
            <label>Email address
              <input data-testid="auth-email-input" type="email" required value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="you@example.com" />
            </label>
            <label>Password
              <input data-testid="auth-password-input" type="password" required value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="••••••••" />
            </label>
            {error && <div className="error" data-testid="auth-error">{error}</div>}
            <button className="primary full" data-testid="auth-submit-button">
              {mode === "login" ? "Sign in" : "Create account"} <ArrowRight size={17} />
            </button>
          </form>
          <button className="text-button" data-testid="auth-mode-toggle"
            onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "New to PulseCare? Create an account" : "Already have an account? Sign in"}
          </button>
          <div className="demo-note">
            <strong>Development access</strong>
            <span>Admin: admin@pulsecare.example.com · Doctor: maya@pulsecare.example.com</span>
            <span>Patient: alex@pulsecare.example.com · Password: PulseCare123!</span>
          </div>
        </div>
      </section>
    </main>
  );
}

/* -------------------------------- dashboard -------------------------------- */
function Dashboard({ session, logout }) {
  const role = session.user.role;
  const navByRole = {
    ADMIN: [["overview", "Overview"], ["doctors", "Doctors"], ["appointments", "Appointments"], ["waitlist", "Waitlist"], ["notifications", "Activity"]],
    DOCTOR: [["overview", "Overview"], ["today", "My schedule"], ["settings", "Settings"]],
    PATIENT: [["overview", "Overview"], ["find-care", "Find care"], ["appointments", "Appointments"], ["waitlist", "Waitlist"], ["medications", "Medications"], ["settings", "Settings"]],
  }[role];
  const [tab, setTab] = useState(navByRole[0][0]);
  return (
    <div className="app-shell">
      <aside>
        <div className="brand"><HeartPulse size={22} /> PulseCare</div>
        <div className="profile">
          <div className="avatar">{session.user.name?.[0]}</div>
          <div>
            <strong data-testid="user-name">{session.user.name}</strong>
            <span>{role.toLowerCase()}</span>
          </div>
        </div>
        <nav>
          {navByRole.map(([n, label]) => (
            <button key={n} className={tab === n ? "active" : ""}
              data-testid={`nav-${n}-button`} onClick={() => setTab(n)}>
              {navIcon(n)}<span>{label}</span>
            </button>
          ))}
        </nav>
        <button className="logout" data-testid="logout-button" onClick={logout}>
          <LogOut size={17} /> Sign out
        </button>
      </aside>
      <main className="dashboard">
        <header>
          <div>
            <span className="eyebrow teal">{role} PORTAL</span>
            <h1>{tab === "overview" ? `Good day, ${session.user.name.split(" ")[0]}` : tab.replace(/-/g, " ")}</h1>
          </div>
          <div className="date-chip">
            <CalendarDays size={16} /> {new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </div>
        </header>
        {role === "PATIENT" && <PatientPortal session={session} tab={tab} setTab={setTab} />}
        {role === "DOCTOR" && <DoctorPortal session={session} tab={tab} />}
        {role === "ADMIN" && <AdminPortal session={session} tab={tab} />}
      </main>
    </div>
  );
}

const navIcon = (n) => {
  const map = {
    overview: <HeartPulse size={17} />, "find-care": <Search size={17} />,
    appointments: <CalendarDays size={17} />, medications: <Pill size={17} />,
    settings: <ShieldCheck size={17} />, today: <CalendarClock size={17} />,
    doctors: <Stethoscope size={17} />, notifications: <Bell size={17} />,
    waitlist: <Timer size={17} />,
  };
  return map[n] || <Users size={17} />;
};

function WelcomeBand({ role, tab }) {
  return (
    <section className="welcome-band">
      <div>
        <span className="eyebrow">{tab === "overview" ? "YOUR CARE JOURNEY" : "WORKSPACE"}</span>
        <h2>
          {role === "PATIENT"
            ? "Your health, in good hands."
            : role === "DOCTOR"
            ? "The day is yours to lead."
            : "Care operations, clearly."}
        </h2>
        <p>
          {role === "PATIENT"
            ? "Find the right specialist and keep every follow-up close."
            : role === "DOCTOR"
            ? "A clear view of every patient, every conversation."
            : "Manage doctors, availability and system activity."}
        </p>
      </div>
      <div className="band-icon">{role === "PATIENT" ? <HeartPulse size={54} /> : <Stethoscope size={54} />}</div>
    </section>
  );
}

/* --------------------------------- patient --------------------------------- */
function PatientPortal({ session, tab, setTab }) {
  const headers = auth(session.token);
  const [appointments, setAppointments] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [selected, setSelected] = useState(null);
  const refresh = useCallback(async () => {
    const r = await client.get("/appointments", headers);
    setAppointments(r.data);
  }, [session.token]);
  useEffect(() => {
    refresh();
    client.get("/doctors", headers).then((r) => setDoctors(r.data));
  }, [refresh]);

  return (
    <>
      <WelcomeBand role="PATIENT" tab={tab} />
      {tab === "find-care" && <BookingFlow doctors={doctors} headers={headers} onBooked={refresh} />}
      {tab === "medications" && <MedicationsView headers={headers} appointments={appointments} />}
      {tab === "waitlist" && <PatientWaitlistView headers={headers} />}
      {tab === "settings" && <CalendarSettings headers={headers} />}
      {(tab === "overview" || tab === "appointments") && (
        selected ? (
          <AppointmentDetails id={selected} headers={headers} role="PATIENT" onBack={() => setSelected(null)} onChange={refresh} />
        ) : (
          <AppointmentList appointments={appointments} role="PATIENT" onOpen={setSelected} onFind={() => setTab("find-care")} />
        )
      )}
      <SafetyNote />
    </>
  );
}

function AppointmentList({ appointments, role, onOpen, onFind }) {
  const upcoming = appointments.filter((a) => new Date(a.start) >= new Date() && a.status !== "CANCELLED");
  return (
    <section className="content-grid">
      <div className="section-heading">
        <div>
          <span className="eyebrow teal">SCHEDULE</span>
          <h2>{role === "PATIENT" ? "Your appointments" : "My schedule"}</h2>
        </div>
        {onFind && role === "PATIENT" && (
          <button className="primary" data-testid="find-doctor-button" onClick={onFind}>
            Find a doctor <ArrowRight size={16} />
          </button>
        )}
      </div>
      {appointments.length ? (
        <div className="appointment-list">
          {appointments.map((a) => (
            <button className="appointment" key={a.id} data-testid={`appointment-${a.id}`} onClick={() => onOpen(a.id)}>
              <div className="appointment-date">
                <strong>{new Date(a.start).toLocaleDateString("en-US", { day: "2-digit" })}</strong>
                <span>{new Date(a.start).toLocaleDateString("en-US", { month: "short" })}</span>
              </div>
              <div className="appointment-info">
                <strong>{role === "PATIENT" ? a.doctor_name : a.patient_name}</strong>
                <span>{a.symptoms?.chief_complaint || "Consultation"} · {a.status}</span>
              </div>
              <div className="appointment-time">
                <Clock3 size={15} />
                {new Date(a.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty" data-testid="appointments-empty">
          <CalendarDays size={30} /><strong>No appointments yet</strong>
          <span>{role === "PATIENT" ? "Find a doctor to get started." : "You have no scheduled visits."}</span>
        </div>
      )}
    </section>
  );
}

/* --------------------------- booking flow --------------------------- */
function BookingFlow({ doctors, headers, onBooked }) {
  const [doctor, setDoctor] = useState(null);
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState([]);
  const [hold, setHold] = useState(null);
  const [message, setMessage] = useState("");
  const [waitlistPrompt, setWaitlistPrompt] = useState(null);
  const [symptoms, setSymptoms] = useState({
    chief_complaint: "", symptoms: "", symptom_duration: "", severity: "Medium", additional_notes: "",
  });

  useEffect(() => {
    if (doctor && date) {
      client.get(`/doctors/${doctor.id}/availability`, { ...headers, params: { date } })
        .then((r) => setSlots(r.data)).catch(() => setSlots([]));
    }
  }, [doctor, date]);

  const holdSlot = async (slot) => {
    setMessage("");
    setWaitlistPrompt(null);
    try {
      const r = await client.post("/appointments/hold", { doctor_id: doctor.id, ...slot }, headers);
      setHold(r.data);
      setMessage("Slot held for 5 minutes. Complete the symptoms form to confirm.");
    } catch (e) {
      const detail = e.response?.data?.detail || "This slot is no longer available.";
      setMessage(detail);
      if (e.response?.status === 409) {
        setWaitlistPrompt(slot);
      }
      // refresh slots on conflict
      const r = await client.get(`/doctors/${doctor.id}/availability`, { ...headers, params: { date } });
      setSlots(r.data);
    }
  };

  const joinWaitlist = async () => {
    try {
      await client.post("/waitlist", { doctor_id: doctor.id, ...waitlistPrompt }, headers);
      setMessage("You're on the waitlist. We'll email you if this slot opens up.");
      setWaitlistPrompt(null);
    } catch (e) {
      setMessage(e.response?.data?.detail || "Could not join the waitlist.");
    }
  };

  const confirm = async (e) => {
    e.preventDefault();
    try {
      await client.post("/appointments/confirm", { hold_id: hold.id, ...symptoms }, headers);
      setHold(null);
      setDoctor(null);
      setDate("");
      setSlots([]);
      setSymptoms({ chief_complaint: "", symptoms: "", symptom_duration: "", severity: "Medium", additional_notes: "" });
      setMessage("Appointment confirmed. Your doctor has been notified.");
      onBooked();
    } catch (e) {
      setMessage(e.response?.data?.detail || "Could not confirm the appointment.");
    }
  };

  return (
    <section className="content-grid">
      <div className="section-heading">
        <div><span className="eyebrow teal">DIRECTORY</span><h2>Find your care team</h2></div>
      </div>
      <div className="doctor-grid">
        {doctors.map((d) => (
          <button className={`doctor-card ${doctor?.id === d.id ? "selected" : ""}`}
            data-testid={`doctor-${d.id}-card`} key={d.id} onClick={() => setDoctor(d)}>
            <div className="avatar"><Stethoscope size={18} /></div>
            <strong>{d.name}</strong>
            <span>{d.specialization}</span>
            <small>{d.qualification} · {d.experience}</small>
          </button>
        ))}
      </div>
      {doctor && (
        <div className="booking-panel">
          <strong>Choose a time with {doctor.name}</strong>
          <label>Date
            <input data-testid="booking-date-input" type="date" value={date}
              min={new Date().toISOString().slice(0, 10)}
              onChange={(e) => { setDate(e.target.value); setHold(null); }} />
          </label>
          {date && slots.length === 0 && (
            <div className="empty"><span>No availability that day. Try another date.</span></div>
          )}
          {slots.length > 0 && (
            <div className="slot-grid">
              {slots.map((s) => (
                <button className="slot" data-testid={`slot-${s.start}`} key={s.start} onClick={() => holdSlot(s)}>
                  {new Date(s.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                </button>
              ))}
            </div>
          )}
          {hold && (
            <>
              <HoldTimer expiresAt={hold.expires_at} onExpire={() => { setHold(null); setMessage("Your hold has expired. Please pick a slot again."); }} />
              <form className="symptom-form" onSubmit={confirm}>
                <strong>Tell us what brings you in</strong>
                <input data-testid="symptom-chief-complaint" required placeholder="Main concern"
                  value={symptoms.chief_complaint}
                  onChange={(e) => setSymptoms({ ...symptoms, chief_complaint: e.target.value })} />
                <textarea data-testid="symptom-details" required placeholder="Describe your symptoms"
                  value={symptoms.symptoms}
                  onChange={(e) => setSymptoms({ ...symptoms, symptoms: e.target.value })} />
                <input data-testid="symptom-duration" required placeholder="How long have symptoms lasted?"
                  value={symptoms.symptom_duration}
                  onChange={(e) => setSymptoms({ ...symptoms, symptom_duration: e.target.value })} />
                <label>Severity
                  <select data-testid="symptom-severity" value={symptoms.severity}
                    onChange={(e) => setSymptoms({ ...symptoms, severity: e.target.value })}
                    style={{ padding: 12, border: "1px solid var(--line)", borderRadius: 9, background: "#fff" }}>
                    <option>Mild</option>
                    <option>Moderate</option>
                    <option>Severe</option>
                  </select>
                </label>
                <textarea data-testid="symptom-notes" placeholder="Anything else the doctor should know? (optional)"
                  value={symptoms.additional_notes}
                  onChange={(e) => setSymptoms({ ...symptoms, additional_notes: e.target.value })} />
                <button className="primary" data-testid="confirm-booking-button">
                  Confirm appointment <ArrowRight size={16} />
                </button>
              </form>
            </>
          )}
          {message && <div className="success" data-testid="booking-message">{message}</div>}
          {waitlistPrompt && (
            <div className="booking-panel" style={{ borderColor: "#f1a43b", padding: 16 }}>
              <strong>Join the waitlist for {new Date(waitlistPrompt.start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}?</strong>
              <p className="muted">We'll notify you by email as soon as this slot opens up. You'll then have a short window to claim it.</p>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="primary" data-testid="waitlist-join-button" onClick={joinWaitlist}>Yes, add me</button>
                <button className="slot" data-testid="waitlist-decline-button" onClick={() => setWaitlistPrompt(null)}>No thanks</button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function HoldTimer({ expiresAt, onExpire }) {
  const [left, setLeft] = useState(Math.max(0, new Date(expiresAt) - new Date()));
  useEffect(() => {
    const t = setInterval(() => {
      const d = new Date(expiresAt) - new Date();
      if (d <= 0) { onExpire(); clearInterval(t); }
      setLeft(Math.max(0, d));
    }, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  const min = Math.floor(left / 60000);
  const sec = Math.floor((left % 60000) / 1000).toString().padStart(2, "0");
  return (
    <div className="success" data-testid="hold-timer" style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Timer size={16} /> Slot reserved for {min}:{sec}
    </div>
  );
}

/* --------------------------- appointment details --------------------------- */
function AppointmentDetails({ id, headers, role, onBack, onChange }) {
  const [item, setItem] = useState(null);
  const [meds, setMeds] = useState([]);
  const [reschedule, setReschedule] = useState(false);
  const load = () => {
    client.get(`/appointments/${id}`, headers).then((r) => setItem(r.data));
    client.get(`/appointments/${id}/medications`, headers).then((r) => setMeds(r.data)).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [id]);
  if (!item) return <div className="empty"><span>Loading…</span></div>;
  const cancel = async () => {
    if (!window.confirm("Cancel this appointment?")) return;
    await client.patch(`/appointments/${id}/cancel`, {}, headers);
    onChange(); onBack();
  };
  const pre = (item.ai_summaries || []).find((x) => x.kind === "PRE_VISIT");
  const post = (item.ai_summaries || []).find((x) => x.kind === "POST_VISIT");
  const clinical = item.clinical;

  return (
    <section className="content-grid">
      <div className="section-heading">
        <div><span className="eyebrow teal">APPOINTMENT</span><h2>{new Date(item.start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</h2></div>
        <button className="text-button" data-testid="back-button" onClick={onBack}><X size={16} /> Close</button>
      </div>

      <div className="booking-panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div>
            <strong>{role === "PATIENT" ? item.doctor_name : item.patient_name}</strong>
            <p className="muted" style={{ marginTop: 4 }}>Status · {item.status}</p>
          </div>
          {item.status === "CONFIRMED" && (
            <div style={{ display: "flex", gap: 8 }}>
              <button className="slot" data-testid="reschedule-button" onClick={() => setReschedule(!reschedule)}><CalendarClock size={14} /> Reschedule</button>
              <button className="slot" style={{ background: "#fdecea", color: "#a63b30" }}
                data-testid="cancel-button" onClick={cancel}><Trash2 size={14} /> Cancel</button>
            </div>
          )}
        </div>
        {reschedule && (
          <RescheduleForm appointment={item} headers={headers} onDone={() => { setReschedule(false); onChange(); onBack(); }} />
        )}
      </div>

      <div className="booking-panel">
        <strong><FileText size={16} /> Your symptoms</strong>
        <p className="muted">{item.symptoms?.chief_complaint} — {item.symptoms?.symptoms}</p>
        <small>Duration: {item.symptoms?.symptom_duration} · Severity: {item.symptoms?.severity}</small>
        {item.symptoms?.additional_notes && <p>{item.symptoms.additional_notes}</p>}
      </div>

      {role === "DOCTOR" && (
        <div className="booking-panel">
          <strong>Pre-visit AI summary</strong>
          <AISummaryView summary={pre} />
        </div>
      )}

      {clinical && (
        <div className="booking-panel">
          <strong>Visit summary</strong>
          {post?.status === "COMPLETED" ? <AISummaryView summary={post} patient /> : <p className="muted">Your doctor's notes are below. AI summary status: {post?.status || "PENDING"}</p>}
          <hr style={{ border: 0, borderTop: "1px solid var(--line)" }} />
          <p><strong>Diagnosis:</strong> {clinical.diagnosis}</p>
          <p><strong>Notes:</strong> {clinical.clinical_notes}</p>
          {clinical.follow_up_instructions && <p><strong>Follow-up:</strong> {clinical.follow_up_instructions}{clinical.follow_up_date ? ` (on ${clinical.follow_up_date})` : ""}</p>}
          {clinical.medications?.length > 0 && (
            <>
              <strong>Prescription</strong>
              <ul className="med-list">
                {clinical.medications.map((m, i) => (
                  <li key={i}><strong>{m.medicine_name}</strong> · {m.dosage} · {m.frequency} · {m.duration}{m.instructions ? ` · ${m.instructions}` : ""}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {role === "PATIENT" && meds.length > 0 && (
        <div className="booking-panel">
          <strong><Pill size={16} /> Upcoming medication reminders</strong>
          <ul className="med-list">
            {meds.slice(0, 8).map((m) => (
              <li key={m.id}>
                <strong>{m.medicine_name}</strong> · {m.dosage} · {new Date(m.scheduled_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
                <span style={{ color: "var(--muted)" }}> · {m.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {role === "DOCTOR" && item.status !== "COMPLETED" && (
        <ClinicalForm id={id} headers={headers} onSaved={() => { onChange(); load(); }} />
      )}
      <SafetyNote />
    </section>
  );
}

function AISummaryView({ summary, patient }) {
  if (!summary) return <p className="muted">Awaiting analysis…</p>;
  if (summary.status === "UNAVAILABLE") return <p className="muted">AI is not configured on this environment.</p>;
  if (summary.status === "FAILED") return <p className="muted">AI summary temporarily unavailable. Please rely on the original information.</p>;
  if (summary.status === "PENDING") return <p className="muted">Generating summary…</p>;
  const p = summary.payload || {};
  return (
    <div>
      {p.urgency_level && <p><strong>Urgency:</strong> <span className={`status ${p.urgency_level.toLowerCase()}`}>{p.urgency_level}</span></p>}
      {p.chief_complaint && <p><strong>Chief complaint:</strong> {p.chief_complaint}</p>}
      {p.summary && <p>{p.summary}</p>}
      {p.suggested_questions?.length > 0 && (
        <>
          <strong>Suggested questions</strong>
          <ul className="med-list">{p.suggested_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </>
      )}
      {p.follow_up_steps?.length > 0 && (
        <>
          <strong>{patient ? "Next steps" : "Follow-up steps"}</strong>
          <ul className="med-list">{p.follow_up_steps.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </>
      )}
    </div>
  );
}

function RescheduleForm({ appointment, headers, onDone }) {
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (date) {
      client.get(`/doctors/${appointment.doctor_id}/availability`, { ...headers, params: { date } })
        .then((r) => setSlots(r.data));
    }
  }, [date]);
  const pick = async (slot) => {
    setError("");
    try {
      await client.patch(`/appointments/${appointment.id}/reschedule`, { start: slot.start, end: slot.end }, headers);
      onDone();
    } catch (e) {
      setError(e.response?.data?.detail || "Could not reschedule.");
    }
  };
  return (
    <div style={{ marginTop: 12 }}>
      <label>Choose a new date
        <input type="date" min={new Date().toISOString().slice(0, 10)}
          data-testid="reschedule-date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      {slots.length > 0 && (
        <div className="slot-grid" style={{ marginTop: 10 }}>
          {slots.map((s) => (
            <button className="slot" key={s.start} data-testid={`reschedule-slot-${s.start}`} onClick={() => pick(s)}>
              {new Date(s.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
            </button>
          ))}
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

/* --------------------------- doctor clinical form --------------------------- */
function ClinicalForm({ id, headers, onSaved }) {
  const [form, setForm] = useState({
    clinical_notes: "", diagnosis: "", follow_up_instructions: "", follow_up_date: "",
  });
  const [meds, setMeds] = useState([]);
  const [message, setMessage] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      await client.post(`/appointments/${id}/clinical-notes`, {
        ...form, medications: meds,
      }, headers);
      setMessage("Visit completed. Follow-up scheduled.");
      onSaved();
    } catch (e) {
      setMessage(e.response?.data?.detail || "Could not save the visit.");
    }
  };
  const addMed = () => setMeds([...meds, { medicine_name: "", dosage: "", frequency: "", duration: "", instructions: "" }]);
  const updateMed = (i, k, v) => setMeds(meds.map((m, idx) => idx === i ? { ...m, [k]: v } : m));
  const removeMed = (i) => setMeds(meds.filter((_, idx) => idx !== i));

  return (
    <form className="booking-panel symptom-form" onSubmit={submit}>
      <strong>Clinical notes</strong>
      <textarea required data-testid="clinical-notes-input" placeholder="Assessment and clinical findings"
        value={form.clinical_notes} onChange={(e) => setForm({ ...form, clinical_notes: e.target.value })} />
      <input required data-testid="diagnosis-input" placeholder="Diagnosis"
        value={form.diagnosis} onChange={(e) => setForm({ ...form, diagnosis: e.target.value })} />
      <strong>Prescription</strong>
      {meds.map((m, i) => (
        <div key={i} className="med-row" data-testid={`med-row-${i}`}>
          <input placeholder="Medicine" value={m.medicine_name} data-testid={`med-name-${i}`}
            onChange={(e) => updateMed(i, "medicine_name", e.target.value)} />
          <input placeholder="Dosage" value={m.dosage} data-testid={`med-dosage-${i}`}
            onChange={(e) => updateMed(i, "dosage", e.target.value)} />
          <input placeholder="Frequency" value={m.frequency} data-testid={`med-frequency-${i}`}
            onChange={(e) => updateMed(i, "frequency", e.target.value)} />
          <input placeholder="Duration" value={m.duration} data-testid={`med-duration-${i}`}
            onChange={(e) => updateMed(i, "duration", e.target.value)} />
          <input placeholder="Instructions" value={m.instructions}
            onChange={(e) => updateMed(i, "instructions", e.target.value)} />
          <button type="button" className="slot" data-testid={`med-remove-${i}`} onClick={() => removeMed(i)}><Trash2 size={13} /></button>
        </div>
      ))}
      <button type="button" className="slot" data-testid="add-medication-button" onClick={addMed}><Plus size={13} /> Add medication</button>
      <textarea data-testid="follow-up-input" placeholder="Follow-up instructions"
        value={form.follow_up_instructions} onChange={(e) => setForm({ ...form, follow_up_instructions: e.target.value })} />
      <input type="date" data-testid="follow-up-date" placeholder="Follow-up date"
        value={form.follow_up_date} onChange={(e) => setForm({ ...form, follow_up_date: e.target.value })} />
      <button className="primary" data-testid="save-clinical-notes-button">Complete visit <ArrowRight size={16} /></button>
      {message && <div className="success">{message}</div>}
    </form>
  );
}

/* --------------------------- doctor portal --------------------------- */
function DoctorPortal({ session, tab }) {
  const headers = auth(session.token);
  const [appointments, setAppointments] = useState([]);
  const [selected, setSelected] = useState(null);
  const refresh = useCallback(() => client.get("/appointments", headers).then((r) => setAppointments(r.data)), [session.token]);
  useEffect(() => { refresh(); }, [refresh]);
  return (
    <>
      <WelcomeBand role="DOCTOR" tab={tab} />
      {tab === "settings" ? <CalendarSettings headers={headers} /> :
        selected ? (
          <AppointmentDetails id={selected} headers={headers} role="DOCTOR" onBack={() => setSelected(null)} onChange={refresh} />
        ) : (
          <AppointmentList appointments={appointments} role="DOCTOR" onOpen={setSelected} />
        )}
      <SafetyNote />
    </>
  );
}

/* --------------------------- admin portal --------------------------- */
function AdminPortal({ session, tab }) {
  const headers = auth(session.token);
  const [overview, setOverview] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [notifs, setNotifs] = useState([]);
  const loadAll = () => {
    client.get("/admin/overview", headers).then((r) => setOverview(r.data));
    client.get("/admin/doctors", headers).then((r) => setDoctors(r.data));
    client.get("/admin/appointments", headers).then((r) => setAppointments(r.data));
    client.get("/admin/notifications", headers).then((r) => setNotifs(r.data));
  };
  useEffect(() => { loadAll(); }, []);
  return (
    <>
      <WelcomeBand role="ADMIN" tab={tab} />
      {tab === "overview" && (
        <>
          <div className="metrics">
            {[["patients", "Patients"], ["doctors", "Active doctors"], ["appointments", "Appointments"], ["failed_integrations", "Failed emails"]].map(([k, l]) => (
              <div className="metric" data-testid={`metric-${k}`} key={k}>
                <span>{l}</span>
                <strong>{overview?.[k] ?? "—"}</strong>
                <small>Across PulseCare</small>
              </div>
            ))}
          </div>
          <div className="empty admin-empty"><ShieldCheck size={28} /><strong>All systems are ready</strong><span>Use the navigation to manage doctors, appointments and activity.</span></div>
        </>
      )}
      {tab === "doctors" && <DoctorAdmin doctors={doctors} headers={headers} onChange={loadAll} />}
      {tab === "appointments" && (
        <section className="content-grid">
          <div className="section-heading"><div><span className="eyebrow teal">SYSTEM</span><h2>All appointments</h2></div></div>
          <div className="appointment-list">
            {appointments.map((a) => (
              <div className="appointment" key={a.id} data-testid={`admin-appt-${a.id}`}>
                <div className="appointment-date"><strong>{new Date(a.start).toLocaleDateString([], { day: "2-digit" })}</strong><span>{new Date(a.start).toLocaleDateString([], { month: "short" })}</span></div>
                <div className="appointment-info"><strong>{a.status}</strong><span>Doctor: {a.doctor_id.slice(0, 8)} · Patient: {a.patient_id.slice(0, 8)}</span></div>
                <div className="appointment-time"><Clock3 size={14} /> {new Date(a.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
              </div>
            ))}
            {!appointments.length && <div className="empty"><span>No appointments yet.</span></div>}
          </div>
        </section>
      )}
      {tab === "waitlist" && <AdminWaitlistView headers={headers} />}
      {tab === "notifications" && (
        <section className="content-grid">
          <div className="section-heading"><div><span className="eyebrow teal">ACTIVITY</span><h2>Notifications & background jobs</h2></div></div>
          <div className="appointment-list">
            {notifs.slice(0, 60).map((n) => (
              <div className="appointment" key={n.id} data-testid={`notif-${n.id}`}>
                <div className="appointment-info">
                  <strong>{n.kind}</strong>
                  <span>{n.to_email} · {n.subject}</span>
                </div>
                <span className={`status ${n.status.toLowerCase()}`}>{n.status}</span>
              </div>
            ))}
            {!notifs.length && <div className="empty"><span>No notification events yet.</span></div>}
          </div>
        </section>
      )}
      <SafetyNote />
    </>
  );
}

function DoctorAdmin({ doctors, headers, onChange }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "", email: "", specialization: "", qualification: "", experience: "",
    phone: "", work_start: "09:00", work_end: "17:00", slot_duration: 30,
  });
  const [error, setError] = useState("");
  const [leaves, setLeaves] = useState({});
  const [leaveDate, setLeaveDate] = useState({});
  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await client.post("/admin/doctors", form, headers);
      setCreating(false);
      setForm({ name: "", email: "", specialization: "", qualification: "", experience: "", phone: "", work_start: "09:00", work_end: "17:00", slot_duration: 30 });
      onChange();
    } catch (e) {
      setError(e.response?.data?.detail || "Could not create doctor.");
    }
  };
  const loadLeaves = async (id) => {
    const r = await client.get(`/admin/doctors/${id}/leaves`, headers);
    setLeaves((prev) => ({ ...prev, [id]: r.data }));
  };
  const addLeave = async (id) => {
    if (!leaveDate[id]) return;
    const r = await client.post(`/admin/doctors/${id}/leave`, { date: leaveDate[id] }, headers);
    alert(`Leave added. Affected appointments: ${r.data.affected_appointments}`);
    setLeaveDate((prev) => ({ ...prev, [id]: "" }));
    loadLeaves(id);
  };
  const removeLeave = async (id, date) => {
    await client.delete(`/admin/doctors/${id}/leave/${date}`, headers);
    loadLeaves(id);
  };

  return (
    <section className="content-grid">
      <div className="section-heading">
        <div><span className="eyebrow teal">DIRECTORY</span><h2>Doctors ({doctors.length})</h2></div>
        <button className="primary" data-testid="new-doctor-button" onClick={() => setCreating(!creating)}>
          <Plus size={16} /> {creating ? "Cancel" : "New doctor"}
        </button>
      </div>
      {creating && (
        <form className="booking-panel symptom-form" onSubmit={submit}>
          <strong>Create a new doctor</strong>
          <input required data-testid="doctor-name-input" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input required data-testid="doctor-email-input" type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input required data-testid="doctor-spec-input" placeholder="Specialization" value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })} />
          <input required placeholder="Qualification" value={form.qualification} onChange={(e) => setForm({ ...form, qualification: e.target.value })} />
          <input required placeholder="Experience" value={form.experience} onChange={(e) => setForm({ ...form, experience: e.target.value })} />
          <div className="med-row">
            <input placeholder="Work start" value={form.work_start} onChange={(e) => setForm({ ...form, work_start: e.target.value })} />
            <input placeholder="Work end" value={form.work_end} onChange={(e) => setForm({ ...form, work_end: e.target.value })} />
            <input placeholder="Slot mins" type="number" value={form.slot_duration} onChange={(e) => setForm({ ...form, slot_duration: parseInt(e.target.value || 30) })} />
          </div>
          {error && <div className="error">{error}</div>}
          <button className="primary" data-testid="doctor-create-submit">Create doctor</button>
        </form>
      )}
      <div className="doctor-grid">
        {doctors.map((d) => (
          <div className="doctor-card" data-testid={`admin-doctor-${d.id}`} key={d.id}>
            <div className="avatar"><Stethoscope size={18} /></div>
            <strong>{d.name}</strong>
            <span>{d.specialization}</span>
            <small>{d.email}</small>
            <small>{d.work_start} — {d.work_end} · {d.slot_duration}m</small>
            <button className="slot" data-testid={`leave-toggle-${d.id}`} onClick={() => loadLeaves(d.id)}>Manage leave</button>
            {leaves[d.id] && (
              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ display: "flex", gap: 6 }}>
                  <input type="date" data-testid={`leave-date-${d.id}`}
                    value={leaveDate[d.id] || ""}
                    onChange={(e) => setLeaveDate({ ...leaveDate, [d.id]: e.target.value })} />
                  <button type="button" className="slot" data-testid={`leave-add-${d.id}`} onClick={() => addLeave(d.id)}>Add</button>
                </div>
                {leaves[d.id].map((l) => (
                  <div key={l.date} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                    <span>{l.date}</span>
                    <button type="button" data-testid={`leave-remove-${d.id}-${l.date}`} className="text-button" onClick={() => removeLeave(d.id, l.date)}>Remove</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* --------------------------- shared views --------------------------- */
function MedicationsView({ headers, appointments }) {
  const [meds, setMeds] = useState([]);
  useEffect(() => {
    Promise.all(appointments.map((a) => client.get(`/appointments/${a.id}/medications`, headers).then((r) => r.data).catch(() => [])))
      .then((chunks) => setMeds(chunks.flat().sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at))));
  }, [appointments.length]);
  const upcoming = meds.filter((m) => new Date(m.scheduled_at) >= new Date());
  return (
    <section className="content-grid">
      <div className="section-heading"><div><span className="eyebrow teal">CARE PLAN</span><h2>Medication schedule</h2></div></div>
      {upcoming.length ? (
        <div className="appointment-list">
          {upcoming.slice(0, 40).map((m) => (
            <div className="appointment" key={m.id} data-testid={`med-${m.id}`}>
              <div className="appointment-date">
                <strong>{new Date(m.scheduled_at).toLocaleDateString([], { day: "2-digit" })}</strong>
                <span>{new Date(m.scheduled_at).toLocaleDateString([], { month: "short" })}</span>
              </div>
              <div className="appointment-info">
                <strong>{m.medicine_name}</strong>
                <span>{m.dosage}{m.instructions ? ` · ${m.instructions}` : ""}</span>
              </div>
              <div className="appointment-time">
                <Clock3 size={14} /> {new Date(m.scheduled_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty"><Pill size={24} /><strong>No medication reminders yet</strong><span>Your doctor's prescription will appear here after your visit.</span></div>
      )}
    </section>
  );
}

function CalendarSettings({ headers }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => client.get("/calendar/status", headers).then((r) => setStatus(r.data)).catch(() => setStatus({ configured: false, connected: false }));
  useEffect(() => { load(); }, []);
  const connect = async () => {
    setBusy(true);
    try {
      const r = await client.get("/calendar/google/connect", headers);
      window.location.href = r.data.url;
    } catch (e) {
      alert(e.response?.data?.detail || "Google Calendar is not configured on the server.");
    } finally {
      setBusy(false);
    }
  };
  const disconnect = async () => { await client.delete("/calendar/google/disconnect", headers); load(); };
  if (!status) return <div className="empty"><span>Loading…</span></div>;
  return (
    <section className="content-grid">
      <div className="section-heading"><div><span className="eyebrow teal">INTEGRATIONS</span><h2>Google Calendar</h2></div></div>
      <div className="booking-panel">
        {!status.configured && <p className="muted">Google Calendar is not configured on this server. Add <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code> and <code>GOOGLE_REDIRECT_URI</code> to enable this feature.</p>}
        {status.configured && !status.connected && (
          <>
            <p>Connect your Google account so PulseCare can add appointments to your calendar automatically.</p>
            <button className="primary" data-testid="calendar-connect-button" disabled={busy} onClick={connect}>Connect Google Calendar</button>
          </>
        )}
        {status.connected && (
          <>
            <p>Your Google Calendar is connected. New bookings will be added automatically.</p>
            <button className="slot" data-testid="calendar-disconnect-button" onClick={disconnect}>Disconnect</button>
          </>
        )}
      </div>
    </section>
  );
}

function SafetyNote() {
  return (
    <div className="safety-note">
      <ShieldCheck size={18} />
      <span>AI-generated summaries are informational and always reviewed by your healthcare professional. They are not a diagnosis or medical advice.</span>
    </div>
  );
}

function PatientWaitlistView({ headers }) {
  const [entries, setEntries] = useState([]);
  const [message, setMessage] = useState("");
  const [claiming, setClaiming] = useState(null);
  const [symptoms, setSymptoms] = useState({
    chief_complaint: "", symptoms: "", symptom_duration: "", severity: "Medium", additional_notes: "",
  });
  const load = () => client.get("/waitlist/mine", headers).then((r) => setEntries(r.data));
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);

  const cancel = async (id) => {
    if (!window.confirm("Remove from the waitlist?")) return;
    await client.delete(`/waitlist/${id}`, headers);
    load();
  };
  const claim = async (e) => {
    e.preventDefault();
    try {
      await client.post(`/waitlist/${claiming.id}/claim`, symptoms, headers);
      setMessage("Slot claimed! Your appointment is confirmed.");
      setClaiming(null);
      load();
    } catch (err) {
      setMessage(err.response?.data?.detail || "Could not claim the slot.");
    }
  };

  return (
    <section className="content-grid">
      <div className="section-heading"><div><span className="eyebrow teal">WAITLIST</span><h2>Your waitlist requests</h2></div></div>
      {message && <div className="success" data-testid="waitlist-message">{message}</div>}
      {entries.length ? (
        <div className="appointment-list">
          {entries.map((w) => (
            <div className="appointment" key={w.id} data-testid={`waitlist-${w.id}`}>
              <div className="appointment-date">
                <strong>{new Date(w.requested_start).toLocaleDateString([], { day: "2-digit" })}</strong>
                <span>{new Date(w.requested_start).toLocaleDateString([], { month: "short" })}</span>
              </div>
              <div className="appointment-info">
                <strong>{w.doctor_name}</strong>
                <span>{new Date(w.requested_start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
                {w.status === "NOTIFIED" && <ClaimCountdown expiresAt={w.claim_expires_at} onExpire={load} />}
              </div>
              <span className={`status ${w.status.toLowerCase()}`}>{w.status}</span>
              {w.status === "NOTIFIED" && (
                <button className="primary" data-testid={`claim-${w.id}`} onClick={() => setClaiming(w)}>
                  Claim <ArrowRight size={14} />
                </button>
              )}
              {(w.status === "WAITING" || w.status === "NOTIFIED") && (
                <button className="slot" data-testid={`waitlist-cancel-${w.id}`} onClick={() => cancel(w.id)}>
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="empty" data-testid="waitlist-empty">
          <Timer size={26} /><strong>You're not on any waitlists</strong>
          <span>When a slot is unavailable, we'll offer to add you to the waitlist automatically.</span>
        </div>
      )}
      {claiming && (
        <form className="booking-panel symptom-form" onSubmit={claim}>
          <strong>Claim {new Date(claiming.requested_start).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} with {claiming.doctor_name}</strong>
          <input required data-testid="claim-chief-complaint" placeholder="Main concern" value={symptoms.chief_complaint} onChange={(e) => setSymptoms({ ...symptoms, chief_complaint: e.target.value })} />
          <textarea required data-testid="claim-symptoms" placeholder="Describe your symptoms" value={symptoms.symptoms} onChange={(e) => setSymptoms({ ...symptoms, symptoms: e.target.value })} />
          <input required data-testid="claim-duration" placeholder="Duration" value={symptoms.symptom_duration} onChange={(e) => setSymptoms({ ...symptoms, symptom_duration: e.target.value })} />
          <label>Severity
            <select value={symptoms.severity} onChange={(e) => setSymptoms({ ...symptoms, severity: e.target.value })}>
              <option>Mild</option><option>Moderate</option><option>Severe</option>
            </select>
          </label>
          <button className="primary" data-testid="claim-submit">Confirm claim <ArrowRight size={16} /></button>
          <button type="button" className="slot" onClick={() => setClaiming(null)}>Cancel</button>
        </form>
      )}
    </section>
  );
}

function ClaimCountdown({ expiresAt, onExpire }) {
  const [left, setLeft] = useState(Math.max(0, new Date(expiresAt) - new Date()));
  useEffect(() => {
    const t = setInterval(() => {
      const d = new Date(expiresAt) - new Date();
      if (d <= 0) { onExpire(); clearInterval(t); }
      setLeft(Math.max(0, d));
    }, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  const min = Math.floor(left / 60000);
  const sec = Math.floor((left % 60000) / 1000).toString().padStart(2, "0");
  return <small style={{ color: "var(--teal)", fontWeight: 700 }}>Claim before {min}:{sec}</small>;
}

function AdminWaitlistView({ headers }) {
  const [entries, setEntries] = useState([]);
  useEffect(() => {
    client.get("/admin/waitlist", headers).then((r) => setEntries(r.data));
  }, []);
  return (
    <section className="content-grid">
      <div className="section-heading"><div><span className="eyebrow teal">SYSTEM</span><h2>Waitlist ({entries.length})</h2></div></div>
      {entries.length ? (
        <div className="appointment-list">
          {entries.map((w) => (
            <div className="appointment" key={w.id} data-testid={`admin-waitlist-${w.id}`}>
              <div className="appointment-date">
                <strong>{new Date(w.requested_start).toLocaleDateString([], { day: "2-digit" })}</strong>
                <span>{new Date(w.requested_start).toLocaleDateString([], { month: "short" })}</span>
              </div>
              <div className="appointment-info">
                <strong>{w.patient_name} → {w.doctor_name}</strong>
                <span>{new Date(w.requested_start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
              </div>
              <span className={`status ${w.status.toLowerCase()}`}>{w.status}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty"><Timer size={22} /><span>No waitlist entries yet.</span></div>
      )}
    </section>
  );
}
