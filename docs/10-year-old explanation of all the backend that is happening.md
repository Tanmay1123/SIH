# Everything the backend does, explained like you're ten

No jargon. No maths. If a word has to be technical, it gets explained in the
next sentence. By the end you'll know what every single piece of the backend
does, in what order, and why it's there.

Read it top to bottom — each part uses the one before it.

---

## Table of contents

1. [The crime we're trying to catch](#1-the-crime-were-trying-to-catch)
2. [The two shapes of cheating](#2-the-two-shapes-of-cheating)
3. [What goes in: two lists](#3-what-goes-in-two-lists)
4. [Step 1 — Turning the lists into a map](#step-1--turning-the-lists-into-a-map)
5. [Step 2 — Finding the circles](#step-2--finding-the-circles)
6. [Step 3 — The invisible strings](#step-3--the-invisible-strings)
7. [Step 4 — Finding the stars](#step-4--finding-the-stars)
8. [Step 5 — Giving everyone a suspicion score](#step-5--giving-everyone-a-suspicion-score)
9. [Step 6 — Making the computer show its working](#step-6--making-the-computer-show-its-working)
10. [Step 7 — A human decides](#step-7--a-human-decides)
11. [Step 8 — The notebook nobody can erase](#step-8--the-notebook-nobody-can-erase)
12. [Step 9 — The letter to the boss](#step-9--the-letter-to-the-boss)
13. [Who is allowed to do what](#who-is-allowed-to-do-what)
14. [The filing cabinet: datasets and runs](#the-filing-cabinet-datasets-and-runs)
15. [Dials, not constants](#dials-not-constants)
16. [The pretend-town machine](#the-pretend-town-machine)
17. [The whole thing in one picture](#the-whole-thing-in-one-picture)
18. [What it still can't do](#what-it-still-cant-do)
19. [Where everything lives](#where-everything-lives)

---

## 1. The crime we're trying to catch

India has a tax called **GST**. Here's the important bit about how it works.

Imagine you run a bakery. You buy ₹100 of flour, and ₹10 of that is tax. Then
you sell a cake for ₹200, and ₹20 of that is tax. You don't hand the government
the whole ₹20 — you already paid ₹10 on the flour, so you hand over ₹10 and
keep the rest. The ₹10 you already paid is called your **input tax credit**.
People say **ITC** for short.

This is fair. You should only pay tax on the value *you* added, not on the flour
someone else already paid tax on.

Now here's the hole.

The government works out how much credit you get **from your invoices** — your
bills. Not from your flour. Nobody comes to your bakery and counts the sacks.
They read the paperwork.

So: **what if you write invoices for flour that never existed?**

You'd get credit for tax you never paid. That's the whole fraud. It's not
clever, it's not high-tech, and it costs India tens of thousands of crores a
year. Our job is to find people doing it, out of millions of honest businesses,
using only the paperwork.

---

## 2. The two shapes of cheating

You can't just make up invoices out of thin air, because an invoice has two
sides. If Company A claims it *bought* something, some Company B has to have
*sold* it. So cheats need friends — or, more often, they need companies they
secretly own that pretend to be friends.

There are two ways they arrange this, and they look completely different on
paper.

### Shape one: the circle

```
        A  ──sells ₹1 crore──▶  B
        ▲                       │
        │                    sells ₹1 crore
     sells ₹1 crore              │
        │                        ▼
        D  ◀──sells ₹1 crore──  C
```

Four companies, all secretly run by the same person. A "sells" to B, B "sells"
to C, C "sells" to D, D "sells" back to A. The same imaginary goods go round and
round the circle. Nothing is ever made, packed, driven anywhere or delivered.
But every single hop creates an invoice, and every invoice creates a tax credit
to claim.

Round and round, faster and faster, credits piling up.

This is called a **circular trading ring**, or just a **ring**. On a map of who
sells to whom, it makes a **loop** — you can start at A, follow the arrows, and
end up back at A.

### Shape two: the star

```
                    ┌──▶ real shop 1
                    ├──▶ real shop 2
     ┌───────┐      ├──▶ real shop 3
     │ MILL  │──────┼──▶ real shop 4
     └───────┘      ├──▶ real shop 5
       ▲            ├──▶ real shop 6
       │            └──▶ real shop 7
   buys nothing
```

One fake company sells to *dozens* of real businesses who want a credit to
claim. It buys from almost nobody, because nothing it "sold" ever existed. It
runs for a few months, issues a mountain of invoices, then stops filing its
returns and disappears. The person behind it opens another one next week.

This is called a **fake invoice mill**.

> **Why "mill"?** A flour mill churns out flour all day. This churns out
> invoices all day. That's the whole joke. The product is paperwork.

Here's the thing that matters: **a star is not a loop**. You can follow those
arrows forever and you'll never get back to where you started. So the clever
loop-finding maths from Shape One is completely blind to it. It needs its own
detector, and it gets one.

Our system looks for both. Everything below is how.

---

## 3. What goes in: two lists

Nothing happens until a tax officer uploads two spreadsheets.

**The companies list** — one row per business:

| what | example |
|---|---|
| its tax ID number (GSTIN) | `27ABCDE1234F1Z5` |
| its name | Guha LLC |
| who runs it | Dev Bhasin |
| where it's registered | 01, Chandra Circle, Ballia |
| when it registered | 2025-06-23 |
| how much money it *says* it makes a year | ₹42,00,000 |

**The invoices list** — one row per bill:

| what | example |
|---|---|
| who sold | `27ABCDE1234F1Z5` |
| who bought | `07XYZAB9876C1Z2` |
| how much | ₹12,50,000 |
| when | 2026-03-14 |
| what for | "Assorted industrial goods" |
| was there an e-way bill? | no |

That last one matters a lot, so: an **e-way bill** is the electronic permit a
truck needs to actually move goods on a road. If you really shipped something,
there's an e-way bill. If you only shipped paperwork, there isn't one.

**The system never invents its own data.** It only ever holds what an officer
uploaded. The one exception is a separate workshop for making pretend data to
test with, and it's kept firmly outside the real console — that's
[section 16](#16-the-pretend-town-machine).

The code that reads those two files is `backend/core/csv_import.py`. It's
picky on purpose: if an invoice mentions a company that isn't in the companies
file, or a date it can't read, it refuses **the whole upload** and tells you
every problem it found. Half-loading a dataset would be worse than not loading
it, because you'd never know what was missing.

---

## Step 1 — Turning the lists into a map

*File: `backend/fraud_engine/graph_builder.py`*

A list of invoices is useless for spotting shapes. So the first thing we do is
draw a map.

- Every **company becomes a dot**.
- Every **invoice becomes an arrow**, pointing from the seller to the buyer.

Mathematicians call this a **graph**: dots (they say *nodes*) joined by arrows
(they say *edges*). It's the same idea as a map of bus routes, or a diagram of
who passed the ball to whom in a football match.

One important trick: if Company A sent Company B **fifty** invoices, we don't
draw fifty arrows. We draw **one** arrow and write on it: *fifty invoices, ₹3
crore total, twelve of them had no e-way bill, first one in April, last one in
September*.

Why bother? Because we're about to ask "is there a path from A back to A?", and
for that question fifty parallel arrows tell you nothing more than one arrow
does. They just make the search fifty times slower. A real dataset can have
millions of invoices, so this squashing is the difference between a search that
finishes and one that doesn't.

---

## Step 2 — Finding the circles

*File: `backend/fraud_engine/cycle_detection.py`*

Now: find every loop in the map.

Sounds easy. It is monstrously hard if you do it the obvious way. On a map of a
few hundred companies with thousands of arrows, "try every possible path" means
more paths than there are atoms in your house. You'd wait a very long time.

So it happens in two stages, and the first stage does almost all the work.

### Stage one: split the map into neighbourhoods (Tarjan's algorithm)

Here's the key insight. **If you're in a loop, then everyone else in that loop
can reach you, and you can reach them.** That has to be true — that's what a
loop *is*.

So before hunting for loops, we group the map into clumps where everybody can
reach everybody else. These clumps are called **strongly connected components**,
which is a mouthful, so think of them as *neighbourhoods where you can walk to
anyone's house and back again*.

A method called **Tarjan's algorithm** finds all these neighbourhoods in one
single sweep of the map. One pass. It's genuinely beautiful — it walks the map
keeping a numbered stack of where it's been, and neighbourhoods just fall out of
the walking.

And then comes the payoff:

> **Any dot that is alone in its own neighbourhood cannot possibly be in a
> loop.** Throw it away. Don't even look at it.

In a real trade network, honest business flows one way — raw materials to
factory to distributor to shop. Nothing comes back. So the overwhelming majority
of companies are alone in their neighbourhood and get discarded instantly. We
might start with 100,000 companies and be left with 500 worth searching.

### Stage two: search inside each neighbourhood (Johnson's algorithm)

Now, and only now, we hunt for actual loops — but only inside those small
surviving neighbourhoods, using something called **Johnson's algorithm**. It's a
careful way of walking every possible circle without ever walking the same one
twice.

We also refuse to look at loops longer than **6 companies**. Two reasons: real
fraud rings are short (every extra member is another person who can talk to the
police), and the searching gets dramatically more expensive with every extra
step allowed.

### What comes out

For every loop found, we bundle up the evidence:

- who's in it, and in what order
- the total money going round
- how similar the amounts are at each hop *(a real negotiated price wobbles;
  fake ones tend to repeat almost exactly)*
- how many of the invoices had no e-way bill
- how many were suspiciously round numbers like exactly ₹50,00,000

That bundle is what an officer eventually reads.

---

## Step 3 — The invisible strings

*Also in `graph_builder.py` and `cycle_detection.py`*

A tax evaluator asked us a very good question once, and it exposed a real hole.

Suppose A sells to B, and B sells to C. That's a straight line. Not a loop.
Nothing to see.

**But what if C and A are run by the same person?**

```
   A ──sells──▶ B ──sells──▶ C
   ╰┈┈┈┈┈┈┈ same director ┈┈┈┈╯
```

Then it *is* a circle. The money gets back to the start — it just doesn't need
an invoice to make the last hop, because it's the same person's pocket at both
ends. And that's the *smarter* way to run the fraud, precisely because it leaves
no closing invoice for anyone to find.

So we add a second kind of arrow to the map. If two companies share a
**registered address** or a **director's name**, we join them with a dashed
arrow called a **control edge**. It means "these two are connected by ownership,
not by trade."

Three rules keep this honest:

1. **A control edge is never counted as trade.** It's marked differently, and
   the money on it is zero, because no money moved.
2. **A loop made only of control edges is meaningless.** Five companies at one
   address isn't a fraud ring, it's an office building. So we insist that every
   reported loop contains **at least one real invoice**.
3. **At most one control hop per loop.** Two or more and you're not describing a
   trading ring any more, you're describing a family tree.

There's one more guard. If a hundred companies share the same address, that's
almost never a shell factory — it's a data problem ("Address not available") or
a filing agent's office. Joining all hundred to each other would add thousands
of meaningless arrows and drown everything. So groups bigger than **12** are
ignored.

On the dataset we tested, this one idea surfaced **92 rings that were completely
invisible before**.

---

## Step 4 — Finding the stars

*File: `backend/fraud_engine/mill_detection.py`*

Now the other shape. Remember, no amount of loop-finding will ever see a mill,
because there's no loop in it.

So this detector doesn't look for shapes at all. It goes down a **checklist**,
like a doctor's list of symptoms.

First, three questions to decide if a company is even worth checking. All three
must be yes:

- Does it sell to **at least 5** different buyers? *(A mill's whole business is
  invoicing lots of people. Two customers isn't a mill.)*
- Does it sell **at least 4× more** than it buys? *(A real trader buys roughly
  what it sells. A mill invoices value it never acquired.)*
- Is the money **over ₹10 lakh**? *(A tiny lopsided company is a small business,
  not an operation worth an officer's day.)*

If it passes all three, we score it out of 100:

| Symptom | Worth | What it means |
|---|---:|---|
| Sells lots, buys nothing | **30** | Where did the goods come from? Nowhere. |
| Most invoices have no e-way bill | **20** | Paper moved. Goods didn't. |
| Sells to many unrelated buyers | **18** | The fan-out shape of a mill. |
| Registered very recently | **12** | Born last spring, already invoicing crores. |
| Declares far less than it invoices | **12** | Says it earns ₹5 lakh, bills ₹5 crore. |
| Amounts are suspiciously round | **8** | ₹50,00,000 exactly. Written, not priced. |

Add them up. Over the threshold (45 out of 100 by default) and it becomes an
alert.

### Why is this a checklist and not clever AI?

Because being honest matters more than looking clever.

The machine-learning model you'll meet in the next section was trained on ring
members. It has **never once seen a labelled mill**. If we fed it a mill anyway,
it would produce a confident-looking number with absolutely nothing behind it —
a guess wearing a lab coat. That's worse than useless in something that
accuses real businesses.

So the mill detector is deliberately, boringly explicit. Every score can be read
back as the reasons that made it, in plain sentences. And the moment officers
have confirmed and cleared enough mills, those decisions become training data —
and this checklist becomes the score a real model has to *beat*.

On our test dataset it found **11 mills** that nothing else in the system could
have seen.

---

## Step 5 — Giving everyone a suspicion score

*File: `backend/fraud_engine/risk_scoring.py`*

We now have a pile of loops. Here's the problem: **most of them are innocent.**

Genuine businesses trade both ways all the time. A shop sells unsold stock back
to its supplier. Two branches of the same chain swap inventory. Three retailers
do mutual transfers. Every one of those makes a real, honest loop.

If we handed an officer every loop we found, we'd be wasting their life. So
something has to sort the loops so the real fraud is at the top.

That something is a machine-learning model. Here's how it actually works.

### First: turn each company into 17 numbers

You can't hand a computer a company. You hand it numbers. So for each company we
work out 17 things:

**About the business itself**
1. How many days since it registered
2. How big it *says* it is
3. How much it actually sold
4. How much it actually bought
5. What it says it earns ÷ what it actually invoiced *(a shell says ₹5 lakh and
   bills ₹5 crore)*
6. Money invoiced per day it has existed *(how fast it's going)*
7. How much of what it bought went straight back out again *(a real trader adds
   value — cuts the cloth, assembles the parts. A conduit just passes it on)*

**About its paperwork**
8. What fraction of its invoices had no e-way bill
9. How many other companies share its address
10. How many other companies share its director
11. How many different businesses it deals with
12. What fraction of its amounts are suspiciously round
13. Whether its invoicing came in one sudden burst

**About the loops it sits in**
14. How many loops it's in
15. How short the tightest one is
16. How similar the amounts are going round it
17. How much money is in the biggest one

### Second: the forest of yes/no questions

The model is called **XGBoost**. Ignore the name. Here's what it really is.

Imagine one simple flowchart:

```
Does it have no e-way bills?
    ├─ no  ──▶  probably fine
    └─ yes ──▶  Is it less than a year old?
                   ├─ no  ──▶  hmm, maybe
                   └─ yes ──▶  Does it bill 10× what it declares?
                                  ├─ no  ──▶  suspicious
                                  └─ yes ──▶  very suspicious
```

That's a **decision tree**. One tree on its own is a bit dumb and gets fooled
easily.

So XGBoost builds **hundreds** of them — and here's the clever part, each new
tree is built specifically to fix the mistakes the previous ones made. Tree 1
does its best. Tree 2 looks at what Tree 1 got wrong and focuses there. Tree 3
fixes what 1 and 2 together still get wrong. And so on. It's called
**boosting**, and it's a bit like a class where every new student is told
exactly which questions everyone before them failed.

At the end, all the trees vote, and the answer comes out as a number from 0 to
100: **how likely is this company to be a shell?**

### Third: score the loop, not just the company

A ring is a *conspiracy*. What matters isn't that one member looks dodgy — it's
that **the whole circle** looks wrong. One suspicious company inside an
otherwise ordinary loop is far more likely to be a coincidence.

So a loop's score is the **average** of its members' scores, not the highest
one. Using the highest would let a single unlucky company drag five innocent
ones into a fraud accusation.

### An important rule: it only scores loop members

If a company isn't in any loop, it gets a score of **zero** and is reported as
"not a circular-trade suspect" — not run through the model at all.

That's not laziness. The model was trained *only* on companies inside loops. Ask
it about a company from outside that world and you'd get a confident number
about a situation it was never taught. We'd rather say "we didn't look at this"
than make something up.

### Where the training data comes from

We can't get real GST invoice data — it's confidential taxpayer information,
locked behind government agreements. Nobody hands that to a student project.

So the model is trained on **generated** trade networks where we secretly know
who the fraudsters are, because we planted them. The generator
(`synthetic_network.py`) builds an honest economy — raw materials to factories
to distributors to shops — and then deliberately plants both real fraud rings
*and* honest-but-loopy businesses, so the model is forced to learn the
difference rather than just learning "in a loop = guilty."

It's also trained on **different randomly generated worlds** from the one it's
tested on, so it can't have memorised anything.

---

## Step 6 — Making the computer show its working

*Also in `risk_scoring.py`*

A number is not enough.

If the screen says **"Risk: 87"** and nothing else, an officer has two choices:
believe a computer they can't question, or ignore it. Neither is any good. You
cannot start legal proceedings against a real business on the strength of a
number nobody can explain.

So every score comes with its reasons, worked out using a method called
**SHAP**.

The idea behind SHAP comes from something completely different: **splitting a
prize fairly among a team**. If five people worked together and won ₹100, how
much did each person actually contribute? The fair answer is to check what the
team would have scored without each person, in every possible combination. SHAP
does exactly that, but with clues instead of teammates: *how much did "no e-way
bills" actually push this score up, compared to a world where we didn't know
that?*

The answers get turned into English sentences:

> - Declared a turnover of ₹42 lakh, covering just 3% of the ₹14.2 crore it has
>   actually invoiced.
> - 96% of its invoices moved with no e-way bill, so paper changed hands but no
>   goods did.
> - Registered 84 days ago yet already invoicing at volume.
> - Shares a registered address with 4 other companies in this loop.

**Nothing here is written by an AI language model.** Every sentence is built
from real numbers pulled from the actual data. There is no step anywhere in this
system where something makes up prose about a business.

---

## Step 7 — A human decides

*Files: `backend/fraud_engine/views.py`, `models.py`*

Now the alert reaches an officer, and this is the part the whole project is
really about.

The officer looks at the loop, the map, the invoices, the reasons — and does one
of two things:

- **Confirm it.** Yes, this is fraud. Start proceedings.
- **Clear it.** No. This is a genuine business. Here's why.

Clearing isn't a shrug. You have to pick a reason from a fixed list — *genuine
two-way trade*, *group companies*, *already investigated*, *data error*, and so
on — and you can add a note.

### Why "clear" is the important one

Before this existed, the system could only ever be told it was **right**. An
officer could confirm a ring, but there was no way at all to say "you were
wrong about this one." So every mistake it made, it made forever.

Each clearing is a **negative example** — a case labelled by a real expert
saying *this pattern is not fraud*. Collect enough of those and you can retrain
the model on real human judgement instead of made-up data. That is the loop
closing, and it's exactly what the evaluators meant by "human in the loop."

### Decisions carry forward

Run detection again next week and you shouldn't have to re-judge everything you
already judged. So each alert gets a **signature** — a fingerprint of which
companies are in it, in a form that doesn't care what order they're listed.
Same companies, same signature, and last week's verdict comes along
automatically.

---

## Step 8 — The notebook nobody can erase

*File: `backend/fraud_engine/ledger.py`*

Every decision goes into an **audit ledger**. Think of it as a notebook where
each page is glued to the one before it.

Here's the trick. Every page contains:

- what happened (which alert, who decided, when, why)
- **a fingerprint of the previous page**

That fingerprint is called a **hash**. A hash is a machine that turns any text
into a fixed jumble of letters and numbers:

```
"Ring 47 confirmed by Anita Rao"  →  a3f5c2b891e4...
"Ring 47 confirmed by Anita Rap"  →  7d2e9f0c4b18...   ← one letter changed!
```

Change *anything* — one letter, one rupee — and the fingerprint changes
completely and unpredictably. You cannot work backwards from a fingerprint to
the text, and you cannot craft text to match a fingerprint you want.

So if someone sneaks into page 5 and quietly changes a name, page 5's
fingerprint changes. But page 6 still carries the **old** fingerprint. The chain
snaps, right there, and points at exactly which page was touched.

Every block also records **which version of the model** made the call and **what
threshold was in force**. So a decision made last March can be read back against
the rules that actually existed last March, not today's.

### The honest limitation

This makes tampering **detectable**, not **impossible**. Someone with full
database access could rewrite every page *and* recompute every fingerprint, and
the chain would look fine.

Stopping *that* needs the fingerprints published somewhere the department
doesn't control — another organisation, or a public blockchain — so there's an
outside copy to compare against. We haven't built that. We're telling you
because a security claim you don't understand the limits of is worse than no
claim at all.

---

## Step 9 — The letter to the boss

*Files: `backend/fraud_engine/reporting.py`, `mailer.py`*

An officer finishes a batch of cases. Now what?

They click **Issue report**, and the system writes a one-page case report and
emails it.

### What's in it

- Which dataset, which detection run, on what date
- Confirmed frauds: company names, GSTINs, how much money, why each was flagged
- Cases cleared, with the reason each was cleared
- Which version of the model made the calls, at what threshold
- A fingerprint of the report itself, so you can prove it wasn't edited later

It's kept to **one page on purpose**. A supervisor with forty of these to read
will read a one-page summary. They will not read eleven pages.

### Where it goes

Two places:

1. **The officer who issued it** — their own copy, at whatever email is on their
   account.
2. **The supervisors** — anyone in the supervisor role who has an email address
   on their account, plus any addresses configured in Settings.

It's sent by **SMTP**, which just means "the normal way computers send email" —
the same protocol your phone's mail app uses. You give the system an email
account's details and it logs in and sends, exactly as you would.

### If email isn't set up yet

Nothing breaks. If no mail server is configured, reports get **printed to the
backend's console window** instead. You can see the entire report, exactly as it
would have arrived, without any credentials existing anywhere. And a report that
fails to send **records why on itself** and can be re-sent later, rather than
throwing an error and losing the work.

### Why the email is hand-written HTML

Email programs are stuck in about 2003. Outlook renders mail with **Microsoft
Word's** engine. Gmail throws away your stylesheet. So the report is built with
every style written directly onto every element, using tables for layout — the
old way, because it's the only way that survives the trip.

### One thing we'd change for real deployment

Right now the report contains taxpayer details, and it's sent over email. In
production it should carry a **link** to a secure page instead, so confidential
information never sits in an inbox. It's written down in the code where the
decision was made, so nobody deploys it by accident.

---

## Who is allowed to do what

*Files: `backend/core/roles.py`, `permissions.py`*

Two roles.

| | Officer | Supervisor |
|---|:---:|:---:|
| Review alerts | ✅ | ✅ |
| **Clear** a case as honest | ✅ | ✅ |
| Run detection, upload data | ✅ | ✅ |
| Issue a report | ✅ | ✅ |
| **Confirm** a case as fraud | ❌ | ✅ |
| See what every officer is doing | ❌ | ✅ |
| Change settings | ❌ | ✅ |

The interesting question is **why the line sits exactly there**.

**Confirming needs a supervisor** because confirming starts recovery
proceedings against a real business. Someone's livelihood. That deserves a
second, more senior pair of eyes.

**Clearing does not**, and that's deliberate. "I looked at this and it's a normal
business" is the single most valuable thing the detector can learn. Put it
behind a supervisor's approval and it would simply never happen — the queue
would silently rot. So we made the safe action easy and the serious action
guarded.

This is enforced on the **server**, not just hidden in the app. An officer who
sends the confirm request by hand still gets refused. Hiding a button is a
courtesy; refusing the request is security.

A couple of small guards: a superuser is always a supervisor (so the very first
account can't lock itself out), and a supervisor can't demote themselves.

---

## The filing cabinet: datasets and runs

*Files: `backend/core/models.py`, `backend/fraud_engine/pipeline.py`*

Two layers of history, and neither ever overwrites anything.

**A dataset** is one upload — one companies file plus one invoices file, with a
name you chose and a date. Upload another one next week and the first doesn't
disappear; you just switch between them with a dropdown. Every dataset keeps its
own companies, its own invoices, its own everything.

**A detection run** is one press of "Run detection" against one dataset. It's a
permanent, dated, named record of what was found, by which model version, at
which threshold. Run it again and you get a *second* run — the first stays
exactly as it was, so you can compare last week's results with this week's.

The alternative — where every upload wipes the last one — means you can never
answer "what did we find in March?" And you can never notice that the March data
looked different.

### One subtle thing worth knowing about

The pipeline builds the map **twice**. Deliberately.

The model's four loop-related clues were learned on a map with **invoice arrows
only**. Adding control edges creates more loops, which would make those four
numbers bigger than anything the model was trained on. It would still print a
confident score — but the score would mean something different from what it
claims.

So: the **clues** come from the invoice-only map, exactly as at training time,
and the **alerts** come from the fuller map with the ownership strings in it.
The score stays honest and the extra rings still get surfaced. Both, instead of
one at the cost of the other.

---

## Dials, not constants

*File: `backend/core/settings_store.py`*

Some numbers in this system aren't facts. They're **policy**.

The biggest one is the **risk threshold** — the score at which an alert counts
as "high risk". Set it low and officers chase everything, including honest
businesses. Set it high and real fraud slips past. That's a trade-off about how
a department spends its time, and it is absolutely not a programmer's decision.

It used to be the number `70`, typed into two different files.

Now it's a setting a supervisor can change from the Settings page, along with
the mill threshold, the longest ring to search for, the organisation's name and
who's copied on reports. Each one resolves in order:

**what's in the database → what's in the `.env` file → the built-in default**

The page tells you which of the three it's currently using. Clear the box and it
falls back to the layer beneath.

**Email passwords are the exception** and stay in the `.env` file only. They're
secrets, and secrets don't go in a database the app can read back into a form.

Every detection run also **stamps the threshold that was in force when it ran**,
so a decision from six months ago can be judged against the policy of six months
ago.

---

## The pretend-town machine

*Files: `backend/fraud_engine/dataset_lab.py`, `lab_views.py`.
Open it at `/lab`.*

You can't test any of this without data. And real data doesn't exist for us.

So there's a workshop, deliberately kept **outside** the console — its own page,
its own look, no case files, no nav rail — that builds a whole pretend economy
to order.

Tell it: 280 companies, 2 circular rings, 3 invoice mills, 6 ambiguous loops, 5
borderline sellers, 14 honest two-way traders. It builds a town.

It plants companies in **four bands**:

| Band | What it is |
|---|---|
| 🔴 **High risk** | Textbook fraud. Every symptom showing. Should be caught. |
| 🟠 **Grey zone** | One or two symptoms each. Genuinely ambiguous — these are the ones that need a human. |
| 🔵 **Suspicious but honest** | Real businesses that form real loops. Flagging these is a *mistake*. |
| ⚪ **Ordinary** | Plain supply-chain trade. Contains no loops at all. |

That third band is the important one. Anyone can build fake data where all the
fraudsters are obvious. If we only did that, our detector would look brilliant
and be worthless. The honest look-alikes are there to catch us out.

### The bit that makes it more than a random-data script

After building the town, it **runs the real detection pipeline over it** — the
same graph builder, the same Tarjan and Johnson, the same mill checklist, the
same XGBoost model — and shows you what came out:

- how many alerts landed high, medium and low
- **how much of the planted fraud was actually found**
- **how many honest businesses got wrongly pushed over the line**

It hands you an **answer key** listing what every company really was. The
detector never sees it.

That's the point. The generator doesn't get to mark its own homework. If it
plants five rings and the detector finds three, the screen says *3 of 5* in
plain sight.

You get the files three ways: download a zip, load them straight into the
console, or just look. Making test data needs no login — it's fabricated
nonsense, and putting it behind the login of the console it exists to fill would
be a circle. Loading it into the real database does need an account, and it goes
in through **exactly the same validation** an officer's upload does. No
shortcuts.

---

## The whole thing in one picture

```
     officer uploads two CSVs
                │
                ▼
     ┌──────────────────────────┐
     │  csv_import.py           │   checks everything, or refuses the lot
     └──────────────────────────┘
                │
                ▼
     ┌──────────────────────────┐
     │  graph_builder.py        │   companies → dots, invoices → arrows
     │                          │   + dashed arrows for shared owners
     └──────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
  ┌───────────┐    ┌──────────────┐
  │  cycle_   │    │  mill_       │   loops ◀──┐  ┌──▶ stars
  │ detection │    │  detection   │            │  │
  └───────────┘    └──────────────┘            │  │
        │                  │                   │  │
        │  Tarjan: throw    │  a checklist      │  │
        │  away everyone    │  with points      │  │
        │  who can't be     │                   │  │
        │  in a loop        │                   │  │
        │  Johnson: search  │                   │  │
        │  what's left      │                   │  │
        ▼                   │                   │  │
  ┌──────────────┐          │                   │  │
  │ risk_scoring │          │                   │  │
  │              │  17 clues → hundreds of      │  │
  │  XGBoost     │  yes/no trees → a score      │  │
  │  + SHAP      │  → and the reasons why       │  │
  └──────────────┘          │                   │  │
        │                   │                   │  │
        └─────────┬─────────┘                   │  │
                  ▼                             │  │
        ┌───────────────────┐                   │  │
        │  pipeline.py      │  one named, dated run
        │                   │  stamped with the model version
        └───────────────────┘
                  │
                  ▼
        ┌───────────────────┐
        │  the officer      │  confirm  →  it was fraud
        │  decides          │  clear    →  it was honest  ◀── the label
        └───────────────────┘                                 we never had
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
  ┌───────────┐      ┌──────────────┐
  │ ledger.py │      │ reporting.py │
  │           │      │  + mailer.py │
  │ a page    │      │              │
  │ glued to  │      │  one page,   │
  │ the last  │      │  by email,   │
  │ one       │      │  to the boss │
  └───────────┘      └──────────────┘
```

---

## What it still can't do

Every honest project has this section. Ours:

- **It's never seen real GST data.** Everything is trained and tested on
  generated networks. Real invoice data is messier in ways we can't predict from
  here.
- **The model doesn't retrain yet.** We now *collect* officer decisions —
  confirmations and clearings — but nothing automatically learns from them. That
  wiring is the obvious next thing to build.
- **The mill detector is a checklist**, and its weights are our judgement, not
  anything learned from data. It's a starting point for a model to beat.
- **The ledger detects tampering, it doesn't prevent it.** Someone with full
  database access could rewrite the whole chain. See
  [Step 8](#step-8--the-notebook-nobody-can-erase).
- **Reports carry taxpayer data over email.** Should be a link to a secure page.
- **Detection runs while you wait.** Fine for a few hundred companies, wrong for
  a few hundred thousand — that needs a background job queue.
- **No login rate-limiting, no token expiry.** Tokens live until logout.
- **We don't log who *looked* at what.** We log every decision, but a system
  holding taxpayer data should record reads too.

---

## Where everything lives

| File | What it does |
|---|---|
| `core/csv_import.py` | Reads the two uploaded files, or refuses them |
| `core/models.py` | Companies, invoices, datasets, settings |
| `core/roles.py`, `permissions.py` | Who's allowed to do what |
| `core/settings_store.py` | Policy dials: database → `.env` → default |
| `core/team_views.py` | Profile, team overview, settings API |
| `fraud_engine/graph_builder.py` | Companies → dots, invoices → arrows, ownership → dashes |
| `fraud_engine/cycle_detection.py` | Tarjan then Johnson: finds the loops |
| `fraud_engine/mill_detection.py` | The checklist that finds the stars |
| `fraud_engine/risk_scoring.py` | 17 clues → XGBoost → score → SHAP reasons |
| `fraud_engine/pipeline.py` | Runs the whole thing as one named, dated run |
| `fraud_engine/ledger.py` | The notebook nobody can erase |
| `fraud_engine/reporting.py` | Writes the one-page case report |
| `fraud_engine/mailer.py` | Sends it, or records why it couldn't |
| `fraud_engine/synthetic_network.py` | Builds pretend worlds to *train* on |
| `fraud_engine/dataset_lab.py` | Builds pretend worlds for *people* to test with |
| `fraud_engine/models.py` | Runs, alerts, ledger blocks, reports |
| `fraud_engine/views.py` | The API the app talks to |
| `fraud_engine/tests.py` | 100 tests that check all of the above |

---

**Want the technical version of all this?** →
[UNDERSTAND_ME.md](UNDERSTAND_ME.md)

**Want to install and run it?** → [../README.md](../README.md)
