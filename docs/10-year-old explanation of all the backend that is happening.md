# Everything the backend does, explained like you're ten

No jargon. If a word has to be technical, it gets explained in the next
sentence. By the end you'll know what every piece of the backend does, in what
order, and why it's there.

Read it top to bottom — each part uses the one before it.

---

## The crime

India has a tax called **GST**. Here's the bit that matters.

You run a bakery. You buy ₹100 of flour, ₹10 of it tax. You sell a cake for
₹200, ₹20 of it tax. You don't hand the government the whole ₹20 — you already
paid ₹10 on the flour, so you hand over ₹10 and keep the rest. That ₹10 is your
**input tax credit**, or **ITC**. Fair enough: you should only pay tax on the
value *you* added.

Now the hole. The government works out your credit **from your invoices**. Not
from your flour. Nobody comes and counts the sacks — they read the paperwork.

So: **what if you write invoices for flour that never existed?**

You get credit for tax you never paid. That's the entire fraud. It isn't
clever, it isn't high-tech, and it costs India tens of thousands of crores a
year. Our job is to find the people doing it among millions of honest
businesses, using nothing but the paperwork.

---

## Two shapes of cheating

You can't invent invoices alone, because an invoice has two sides. If A claims
it *bought* something, some B has to have *sold* it. So cheats need friends — or
companies they secretly own that pretend to be friends.

They arrange this two ways, and on paper the two look nothing alike.

### Shape one: the circle

```
        A  ──sells ₹1 crore──▶  B
        ▲                       │
     sells ₹1 crore          sells ₹1 crore
        │                        ▼
        D  ◀──sells ₹1 crore──  C
```

Four companies, all secretly run by one person. The same imaginary goods go
round and round. Nothing is ever made, packed, or delivered — but every hop
creates an invoice, and every invoice creates a credit to claim.

This is a **circular trading ring**. On a map of who sells to whom it makes a
**loop**: start at A, follow the arrows, end up back at A.

### Shape two: the star

```
                    ┌──▶ real shop 1
     ┌───────┐      ├──▶ real shop 2
     │ MILL  │──────┼──▶ real shop 3
     └───────┘      ├──▶ real shop 4
       ▲            └──▶ …and 20 more
   buys nothing
```

One fake company sells to *dozens* of real businesses who want a credit to
claim. It buys from almost nobody, because nothing it "sold" ever existed. It
runs a few months, issues a mountain of invoices, stops filing, and disappears.
The person behind it opens another next week.

This is a **fake invoice mill**.

> **Why "mill"?** A flour mill churns out flour all day. This churns out
> invoices all day. The product is paperwork.

Here's what matters: **a star is not a loop**. Follow those arrows forever and
you never get back where you started, so the loop-finding maths from Shape One
is completely blind to it. It needs its own detector, and it gets one.

---

## What goes in: two lists

Nothing happens until an officer uploads two spreadsheets.

**Companies** — one row per business: tax ID (GSTIN), name, who runs it, where
it's registered, when it registered, and how much it *says* it makes.

**Invoices** — one row per bill: who sold, who bought, how much, when, what for,
and **whether there was an e-way bill**.

That last one matters a lot. An **e-way bill** is the electronic permit a truck
needs to move goods on a road. Really shipped something? There's an e-way bill.
Only shipped paperwork? There isn't.

`core/csv_import.py` reads these, and it's picky on purpose: if an invoice
mentions a company missing from the companies file, or a date it can't read, it
refuses **the whole upload** and lists every problem. Half-loading a dataset is
worse than not loading it, because you'd never know what was missing.

**The system never invents its own data** — only what an officer uploaded. The
one exception is a workshop for pretend test data, kept firmly outside the real
console; see [the pretend town](#the-pretend-town-machine).

---

## Step 1 — Turning the lists into a map

*`fraud_engine/graph_builder.py`*

A list of invoices is useless for spotting shapes, so first we draw a map.
Every **company becomes a dot**. Every **invoice becomes an arrow** from seller
to buyer.

Mathematicians call this a **graph**: dots joined by arrows. Same idea as a map
of bus routes, or a diagram of who passed the ball to whom.

One trick: if A sent B **fifty** invoices, we draw **one** arrow and write on
it — *fifty invoices, ₹3 crore total, twelve with no e-way bill, April to
September*. We're about to ask "is there a path from A back to A?", and for that
question fifty parallel arrows tell you nothing more than one does. They just
make the search fifty times slower. Real datasets have millions of invoices, so
this squashing is the difference between a search that finishes and one that
doesn't.

---

## Step 2 — Finding the circles

*`fraud_engine/cycle_detection.py`*

Now find every loop. Sounds easy; it's monstrously hard done the obvious way.
On a few hundred companies with thousands of arrows, "try every possible path"
means more paths than there are atoms in your house. So it happens in two
stages, and the first does almost all the work.

### Stage one: split the map into neighbourhoods

The key insight: **if you're in a loop, everyone else in it can reach you, and
you can reach them.** That's what a loop *is*.

So before hunting loops, we group the map into clumps where everybody can reach
everybody else — officially **strongly connected components**, but think of them
as *neighbourhoods where you can walk to anyone's house and back*.
**Tarjan's algorithm** finds them all in one single sweep. Then the payoff:

> **Any dot alone in its own neighbourhood cannot possibly be in a loop.** Throw
> it away without looking at it.

Honest business flows one way — raw materials to factory to distributor to shop,
nothing comes back. So the overwhelming majority of companies are alone and get
discarded instantly. Start with 100,000 companies; be left with 500 worth
searching.

### Stage two: search what's left

Only now do we hunt actual loops, only inside those small survivors, using
**Johnson's algorithm** — a careful way of walking every possible circle without
ever walking the same one twice. We also refuse loops longer than **6
companies**: real rings are short (every extra member is another person who can
talk to the police), and searching gets dramatically more expensive with each
step allowed.

### What comes out

For each loop: who's in it and in what order, the total money going round, how
similar the amounts are at each hop *(real negotiated prices wobble; fake ones
repeat almost exactly)*, how many invoices had no e-way bill, and how many were
suspiciously round numbers like exactly ₹50,00,000.

---

## Step 3 — The invisible strings

*Also `graph_builder.py` and `cycle_detection.py`*

A tax evaluator asked a very good question once, and it exposed a real hole.

A sells to B, B sells to C. A straight line. Not a loop. Nothing to see.

**But what if C and A are run by the same person?**

```
   A ──sells──▶ B ──sells──▶ C
   ╰┈┈┈┈┈┈ same director ┈┈┈┈╯
```

Then it *is* a circle. The money gets back to the start; it just doesn't need an
invoice for the last hop, because it's the same pocket at both ends. And that's
the *smarter* way to run the fraud, precisely because it leaves no closing
invoice to find.

So we add a second kind of arrow. Two companies sharing a **registered address**
or a **director's name** get joined by a dashed **control edge**, meaning "these
two are connected by ownership, not trade."

Three rules keep it honest:

1. **A control edge is never counted as trade.** The money on it is zero,
   because no money moved.
2. **A loop of only control edges is meaningless.** Five companies at one address
   isn't a ring, it's an office building. Every reported loop must contain **at
   least one real invoice**.
3. **At most one control hop per loop.** More than that and you're describing a
   family tree, not a trading ring.

One more guard: if a hundred companies share an address, that's almost never a
shell factory — it's a data problem ("Address not available") or a filing
agent's office. Joining all hundred would add thousands of meaningless arrows,
so groups bigger than **12** are ignored.

On our test data this one idea surfaced **92 rings that were invisible before**.

---

## Step 4 — Finding the stars

*`fraud_engine/mill_detection.py`*

No amount of loop-finding will ever see a mill, because there's no loop in it.
So this detector doesn't look for shapes at all. It works down a **checklist**,
like a doctor's list of symptoms.

First, three questions to decide whether a company is even worth checking. All
three must be yes:

- Sells to **at least 5** different buyers? *(A mill's business is invoicing lots
  of people. Two customers isn't a mill.)*
- Sells **at least 4× more** than it buys? *(A real trader buys roughly what it
  sells. A mill invoices value it never acquired.)*
- Money **over ₹10 lakh**? *(A tiny lopsided company is a small business, not an
  operation worth an officer's day.)*

If it passes all three, we score it out of 100:

| Symptom | Worth | What it means |
|---|---:|---|
| Sells lots, buys nothing | **30** | Where did the goods come from? Nowhere. |
| Most invoices have no e-way bill | **20** | Paper moved. Goods didn't. |
| Sells to many unrelated buyers | **18** | The fan-out shape of a mill. |
| Registered very recently | **12** | Born last spring, already invoicing crores. |
| Declares far less than it invoices | **12** | Says ₹5 lakh, bills ₹5 crore. |
| Amounts suspiciously round | **8** | ₹50,00,000 exactly. Written, not priced. |

Over the threshold (45 by default) and it becomes an alert.

**Why a checklist and not clever AI?** Because being honest matters more than
looking clever. The model in the next section was trained on ring members and
has **never seen a labelled mill**. Feed it one and it produces a
confident-looking number with nothing behind it — a guess wearing a lab coat.
That's worse than useless in something that accuses real businesses.

So this detector is deliberately, boringly explicit: every score reads back as
the reasons that made it. And once officers have confirmed and cleared enough
mills, those decisions become training data — and this checklist becomes the
score a real model has to *beat*.

On our test data it found **11 mills** nothing else could have seen.

---

## Step 5 — A suspicion score

*`fraud_engine/risk_scoring.py`*

We now have a pile of loops, and here's the problem: **most are innocent.**
Genuine businesses trade both ways constantly — a shop returns unsold stock to
its supplier, two branches swap inventory, three retailers do mutual transfers.
Every one makes a real, honest loop. Hand an officer all of them and you waste
their life, so something must sort them with real fraud at the top.

### First: turn each company into 17 numbers

You can't hand a computer a company; you hand it numbers. So for each company:

**The business** — days since registering · how big it says it is · how much it
actually sold · how much it actually bought · what it says it earns ÷ what it
invoiced *(a shell says ₹5 lakh, bills ₹5 crore)* · money invoiced per day it
has existed · how much of what it bought went straight back out *(a real trader
adds value; a conduit just passes it on)*

**The paperwork** — fraction of invoices with no e-way bill · companies sharing
its address · companies sharing its director · how many businesses it deals with
· fraction of amounts suspiciously round · whether invoicing came in one burst

**The loops** — how many it's in · how short the tightest is · how similar the
amounts going round · how much money is in the biggest

### Second: a forest of yes/no questions

The model is called **XGBoost**. Ignore the name. Imagine one flowchart:

```
No e-way bills?
   ├─ no  ──▶ probably fine
   └─ yes ──▶ Less than a year old?
                ├─ no  ──▶ hmm, maybe
                └─ yes ──▶ Bills 10× what it declares?
                             ├─ no  ──▶ suspicious
                             └─ yes ──▶ very suspicious
```

That's a **decision tree**. One alone is dumb and easily fooled, so XGBoost
builds **hundreds** — and here's the clever part, each new tree is built
specifically to fix the mistakes the previous ones made. It's called
**boosting**: like a class where each new student is told exactly which
questions everyone before them failed. All the trees vote, and out comes a
number from 0 to 100.

### Third: score the loop, not the company

A ring is a *conspiracy*. What matters isn't that one member looks dodgy — it's
that **the whole circle** looks wrong. So a loop's score is the **average** of
its members', not the highest. Using the highest would let one unlucky company
drag five innocent ones into a fraud accusation.

A company in no loop scores **zero** and is reported as "not a circular-trade
suspect" — not run through the model at all. The model was trained *only* on
companies inside loops; ask it about one outside that world and you'd get a
confident number about a situation it was never taught. Better to say "we didn't
look at this" than to make something up.

### Where the training data comes from

We can't get real GST data — it's confidential taxpayer information behind
government agreements. So the model trains on **generated** networks where we
secretly know who the fraudsters are, because we planted them. The generator
builds an honest economy, then plants both real rings *and* honest-but-loopy
businesses, forcing the model to learn the difference rather than just "in a
loop = guilty." It's tested on **different** random worlds from the ones it
trained on, so it can't have memorised anything.

---

## Step 6 — Making the computer show its working

*Also `risk_scoring.py`*

A number is not enough. If the screen says **"Risk: 87"** and nothing else, an
officer can either believe a computer they can't question or ignore it. Neither
is any good — you cannot start legal proceedings against a real business on the
strength of a number nobody can explain.

So every score comes with reasons, worked out using **SHAP**. The idea comes
from something unrelated: **splitting a prize fairly**. If five people won ₹100
together, how much did each contribute? The fair answer checks what the team
would have scored without each person, in every combination. SHAP does that with
clues instead of teammates: *how much did "no e-way bills" actually push this
score up, versus a world where we didn't know that?*

The answers become English sentences:

> - Declared ₹42 lakh, covering just 3% of the ₹14.2 crore it has invoiced.
> - 96% of its invoices moved with no e-way bill — paper changed hands, goods
>   didn't.
> - Registered 84 days ago yet already invoicing at volume.
> - Shares a registered address with 4 other companies in this loop.

**Nothing here is written by an AI language model.** Every sentence is built from
real numbers pulled from the actual data. Nowhere in this system does anything
make up prose about a business.

---

## Step 7 — A human decides

*`fraud_engine/views.py`, `models.py`*

The alert reaches an officer, and this is what the project is really about. They
look at the loop, the map, the invoices, the reasons — and either:

- **Confirm it.** This is fraud. Start proceedings.
- **Clear it.** This is a genuine business. Here's why.

Clearing isn't a shrug — you pick a reason from a fixed list (*genuine two-way
trade*, *group companies*, *already investigated*, *data error*) and can add a
note.

**Why "clear" is the important one.** Before it existed, the system could only
ever be told it was **right**. There was no way to say "you were wrong about
this," so every mistake it made, it made forever. Each clearing is a **negative
example** — a case labelled by a real expert saying *this pattern is not fraud*.
Collect enough and you can retrain on human judgement instead of made-up data.
That's the loop closing, and exactly what evaluators mean by "human in the loop."

**Decisions carry forward.** Each alert gets a **signature** — a fingerprint of
which companies are in it, ignoring their order — so next week's run inherits
last week's verdict automatically instead of asking you to judge it twice.

---

## Step 8 — The notebook nobody can erase

*`fraud_engine/ledger.py`*

Every decision goes into an **audit ledger** — a notebook where each page is
glued to the one before. Every page holds what happened (which alert, who
decided, when, why) *and* **a fingerprint of the previous page**.

That fingerprint is a **hash**: a machine that turns any text into a fixed
jumble.

```
"Ring 47 confirmed by Anita Rao"  →  a3f5c2b891e4...
"Ring 47 confirmed by Anita Rap"  →  7d2e9f0c4b18...   ← one letter changed
```

Change *anything* — one letter, one rupee — and the fingerprint changes
completely and unpredictably. You can't work backwards from a fingerprint to the
text, and you can't craft text to match one you want.

So if someone sneaks into page 5 and changes a name, page 5's fingerprint
changes — but page 6 still carries the **old** one. The chain snaps right there
and points at exactly which page was touched.

Every block also records **which model version** made the call and **what
threshold** was in force, so a decision from last March reads back against last
March's rules, not today's.

**The honest limitation:** this makes tampering **detectable**, not
**impossible**. Someone with full database access could rewrite every page *and*
recompute every fingerprint, and the chain would look fine. Stopping that needs
the fingerprints published somewhere the department doesn't control, so there's
an outside copy to compare against. We haven't built that. We're saying so
because a security claim you don't understand the limits of is worse than none.

---

## Step 9 — The report

*`fraud_engine/reporting.py`, `mailer.py`*

An officer finishes a batch of cases. Now what? They generate a **PDF report**,
read it on screen, and send it to a supervisor.

There are **two kinds**, sharing one system:

| | **Run report** | **Company report** |
|---|---|---|
| Covers | one whole detection run | one company |
| Holds | confirmed cases worst-first with the reason for each, money at risk, and what was cleared and why | registration details, trade totals, why its score is what it is, and every alert it appears in |
| Needs a decision first? | written after working the queue | no — *"why does this look clean"* is as fair a question as *"why is this red"* |

Both record which model version made the calls, at what threshold, and carry a
fingerprint of the report itself so you can prove it wasn't edited later.

**Generating and sending are separate on purpose.** A report is written and
hashed into the ledger the moment it's generated, so what was issued is on
record either way. But nothing reaches an inbox until someone presses *Send* and
confirms in a box naming the exact recipients. Almost everything else in this
system can be undone by fixing a row in a table. An email landing in someone's
inbox cannot.

**Where it goes:** the officer who generated it, plus every supervisor with an
email on their account, plus any addresses set in Settings — de-duplicated.

The message is a **short cover note with the PDF attached**, not the whole report
pasted into the body. It used to be the latter, and read as a wall of formatting
rather than a letter.

**If email isn't set up**, nothing breaks: reports print to the backend's console
instead. A report that fails to send **records why on itself** and can be
retried, rather than erroring and losing the work.

> **One thing we'd change for real deployment.** The report carries taxpayer
> details, and email is not a channel confidential data should cross. In
> production it should carry a **link** to a secure page instead. It's written
> down in the code where the decision was made, so nobody deploys it by accident.

---

## Who is allowed to do what

*`core/roles.py`, `permissions.py`*

| | Officer | Supervisor |
|---|:---:|:---:|
| Review alerts | ✅ | ✅ |
| **Clear** a case as honest | ✅ | ✅ |
| Run detection, upload data | ✅ | ✅ |
| Generate a report | ✅ | ✅ |
| **Confirm** a case as fraud | ❌ | ✅ |
| See what every officer is doing | ❌ | ✅ |
| Change settings | ❌ | ✅ |

The interesting question is **why the line sits exactly there**.
**Confirming needs a supervisor** because it starts recovery proceedings against
a real business — someone's livelihood — which deserves a second, more senior
pair of eyes. **Clearing doesn't**, deliberately: "I looked, this is a normal
business" is the most valuable thing the detector can learn, and behind an
approval step it would simply never happen. The safe action is easy; the serious
one is guarded.

This is enforced on the **server**, not just hidden in the app. An officer who
sends the confirm request by hand still gets refused. Hiding a button is a
courtesy; refusing the request is security.

Two small guards: a superuser is always a supervisor (so the first account can't
lock itself out), and a supervisor can't demote themselves.

---

## The filing cabinet: datasets and runs

*`core/models.py`, `fraud_engine/pipeline.py`*

Two layers of history, and neither ever overwrites anything.

**A dataset** is one upload — one companies file plus one invoices file, named
and dated. Upload another next week and the first doesn't disappear; you switch
between them with a dropdown, and each keeps its own companies and invoices.

**A run** is one press of "Run detection": a permanent, dated record of what was
found, by which model version, at which threshold. Run again and you get a
*second* run, so you can compare last week with this week. The alternative —
every upload wiping the last — means you can never answer "what did we find in
March?"

**One subtle thing.** The pipeline builds the map **twice**, deliberately. The
model's four loop-related clues were learned on a map with **invoice arrows
only**. Adding control edges creates more loops, making those numbers bigger
than anything the model saw in training; it would still print a confident score,
but the score would mean something different from what it claims. So the
**clues** come from the invoice-only map, exactly as at training time, and the
**alerts** come from the fuller map with the ownership strings. The score stays
honest *and* the extra rings still surface.

---

## Dials, not constants

*`core/settings_store.py`*

Some numbers here aren't facts. They're **policy**.

The biggest is the **risk threshold** — the score at which an alert counts as
high risk. Set it low and officers chase everything, including honest
businesses. Set it high and real fraud slips past. That's a trade-off about how
a department spends its time, and absolutely not a programmer's decision.

It used to be the number `70`, typed into two different files. Now a supervisor
changes it from the Settings page, along with the mill threshold, the longest
ring to search, and who's copied on reports. Each resolves in order:
**database → `.env` → built-in default**, and the page shows which of the three
it's using.

**Email passwords are the exception** and live in `.env` only. They're secrets,
and secrets don't belong in a database the app can read back into a form.

Every run also **stamps the threshold in force when it ran**, so a decision from
six months ago is judged against six-month-old policy.

---

## The pretend-town machine

*`fraud_engine/dataset_lab.py`, `lab_views.py` — open it at `/lab`*

You can't test any of this without data, and real data doesn't exist for us. So
there's a workshop, deliberately **outside** the console — own page, own look,
no case files — that builds a pretend economy to order.

Tell it: 280 companies, 2 rings, 3 mills, 6 ambiguous loops, 14 honest two-way
traders. It builds a town, planting companies in **four bands**:

| Band | What it is |
|---|---|
| 🔴 **High risk** | Textbook fraud, every symptom showing. Should be caught. |
| 🟠 **Grey zone** | One or two symptoms. Genuinely ambiguous — needs a human. |
| 🔵 **Suspicious but honest** | Real businesses forming real loops. Flagging these is a *mistake*. |
| ⚪ **Ordinary** | Plain supply-chain trade. No loops at all. |

That third band is the important one. Anyone can build fake data where every
fraudster is obvious; a detector tested only on that would look brilliant and be
worthless. The honest look-alikes are there to catch us out.

**What makes it more than a random-data script:** afterwards it **runs the real
detection pipeline over the town** — same graph builder, same Tarjan and
Johnson, same checklist, same model — and reports **how much planted fraud was
actually found** and **how many honest businesses got wrongly flagged**.

It hands you an **answer key** of what every company really was, which the
detector never sees. The generator doesn't mark its own homework: plant five
rings, find three, and the screen says *3 of 5* in plain sight.

Making test data needs no login — it's fabricated nonsense, and putting it
behind the login of the console it exists to fill would be a circle. Loading it
for real does need an account, and goes through **the same validation** an
officer's upload does.

Five ready-made towns are already generated in [`datasets/`](../datasets/), one
per preset, so there's something to load straight after cloning.

---

## What it still can't do

Every honest project has this section. Ours:

- **It's never seen real GST data.** Trained and tested entirely on generated
  networks. Real invoice data is messier in ways we can't predict from here.
- **The model doesn't retrain yet.** We *collect* officer decisions but nothing
  learns from them automatically. That wiring is the obvious next build.
- **The mill detector is a checklist**, its weights our judgement rather than
  anything learned — a starting point for a model to beat.
- **The ledger detects tampering, it doesn't prevent it.** See
  [Step 8](#step-8--the-notebook-nobody-can-erase).
- **Reports carry taxpayer data over email.** Should be a link to a secure page.
- **Detection runs while you wait.** Fine for hundreds of companies, wrong for
  hundreds of thousands — that needs a background job queue.
- **No rate-limiting or token expiry, and we don't log who *looked* at what.**
  We log every decision, but a system holding taxpayer data should record reads.

---

## Where everything lives

In `backend/`, roughly in the order the data flows through them:

| File | What it does |
|---|---|
| `core/csv_import.py` | Reads the two uploaded files, or refuses them |
| `core/models.py` | Companies, invoices, datasets, settings |
| `core/roles.py`, `permissions.py` | Who's allowed to do what |
| `core/settings_store.py` | Policy dials: database → `.env` → default |
| `fraud_engine/graph_builder.py` | Dots, arrows, and the ownership dashes |
| `fraud_engine/cycle_detection.py` | Tarjan then Johnson: finds the loops |
| `fraud_engine/mill_detection.py` | The checklist that finds the stars |
| `fraud_engine/risk_scoring.py` | 17 clues → XGBoost → score → SHAP reasons |
| `fraud_engine/pipeline.py` | Runs it all as one named, dated run |
| `fraud_engine/ledger.py` | The notebook nobody can erase |
| `fraud_engine/reporting.py`, `mailer.py` | Writes both reports, renders the PDF, sends it |
| `fraud_engine/synthetic_network.py` | Pretend worlds to *train* on |
| `fraud_engine/dataset_lab.py` | Pretend worlds for *people* to test with |
| `fraud_engine/views.py` | The API the app talks to |
| `fraud_engine/tests.py` | 126 tests checking all of the above |

---

**The technical version** → [UNDERSTAND_ME.md](UNDERSTAND_ME.md) ·
**Install and run it** → [../README.md](../README.md)
