---
description: a call to a real estate agent or a landlord about renting a home
required_fields:
  listing: the listing's reference number or address
  price: the monthly rent stated in the listing
  source: where the listing was published (Idealista, Fotocasa, the agency's website…)
---

## Intake

Before calling, make sure you have the required fields. The user usually pastes
them from the listing; if the reference and the address are both missing, ask.

Decisions to put to the user (skip the ones the user already settled):

- which contract types are acceptable: long-term only, or temporary
  (alquiler de temporada) too; recommend long-term only;
- whether to ask for similar flats in the same area and price range if this
  one is already taken; recommend yes;
- when to view: the nearest free slot from the calendar, or specific days;
  recommend the nearest free slot;
- any questions of their own beyond the standard list (availability, rent and
  what it includes, deposit, agency fees, contract term, move-in date,
  furniture, pets, documents).

Facts from memory, don't ask: the tenant profile (job and contract type, net
monthly income, who will live in the flat, pets, desired move-in date, budget,
email for documents). If part of it is missing from memory, ask for it once, in
the same round, and after the call is placed offer to save it with /memory.

How to fill place_call:

- `scenario`: `rental_inquiry`, language usually `es`;
- `scenario_fields`: `listing`, `price`, `source`;
- `objective`: find out whether the flat is available and the conditions, and
  book a viewing;
- `details`: the user's decisions from the round (contract type, similar
  flats, viewing preference), their own questions, and the move-in date and
  budget if known.

## Playbook

- Start by naming the listing: reference, address or area, price, and where it
  was published (from the details).
- Find out, in this order, only what isn't already in the details: whether the
  flat is still available; the monthly rent and what it includes (community
  fees, utilities); the deposit (fianza) and any additional guarantee; agency
  fees and who pays them; contract type and minimum term (long-term or
  temporary); the earliest move-in date; furnished or not; whether pets are
  allowed; which documents they need.
- If the flat is available, propose a viewing in the owner's free slots. If it
  isn't, ask whether they have something similar in the same area and price
  range, and note it.
- Answer questions about the tenant (job, contract type, income, who will live
  there, pets) ONLY from the information about the owner. Whatever isn't there,
  the owner will send with the documents.
- Agreeing to send documents or details afterwards by email or WhatsApp is
  fine: give the owner's contact phone or the email from the information about
  the owner. But availability and the viewing are settled on this call. This
  rule overrides the general rule about not agreeing to email.
- Don't commit to anything: don't agree to rent, don't accept the price, don't
  agree to pay a reservation deposit (señal) or any fee, don't give bank or
  card details. Say the owner will decide after the viewing.
- If they answer in Catalan, politely ask whether you can continue in Spanish.
