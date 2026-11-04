# Tenant creation is an operator action, not a portal one

P5-14 (#46) asks for "a customer can be onboarded as a tenant ... without
anybody touching SQL", and for "the portal carries the surface". Those two
sentences pull in different directions for *tenant* creation, and this records
which way it went and why, because the alternative is reasonable and someone
will propose it again.

**Decision.** User administration is a portal surface: tenant-scoped,
admin-gated, `GET/POST /users` and `DELETE /users/{id}`. **Tenant creation is
not a route at all.** It is an operator command, `python -m app.accounts
create-tenant`, which creates the tenant and its first admin in one
transaction and prints the admin's one-time password.

**Why not a route.** Every authenticated surface in this application acts *as a
tenant* — `require_auth` binds `current_tenant_id()` from the session, and the
tenant-admin gate is a role *within* a tenant. The person creating a tenant
belongs to no tenant yet, so neither fits:

- Gated by `AdminDep`, a create-tenant route would mean "an admin of tenant A
  may create tenant B", which is not a permission that exists in P5's model and
  not one any story asks for.
- Ungated, it would let anyone who can reach the portal create tenants. On a
  deployment whose login page is the only thing between the internet and the
  control plane, that is a hole, and a self-serve signup flow is a product
  decision rather than a missing endpoint.
- A third role — a platform operator above all tenants — would fit, and is
  what a real SaaS grows. It needs its own authentication story, its own audit
  actor and its own tests, and inventing it inside this ticket would be the
  largest unasked-for change in the phase.

So the authority that creates a tenant is shell access to the control plane,
which is exactly who should have it today: a single-operator portal where the
operator deploys the stack. That is a real authorization decision, not an
absence of one.

**Why this still satisfies the ticket.** "Without anybody touching SQL" is the
requirement, and the requirement is met: the command validates the slug, writes
both rows in one transaction, cannot create a tenant with no admin, and leaves
an audit row. What it replaces is a hand-written `INSERT` whose correctness
nobody checked. "The portal carries the surface" is satisfied for the part a
*customer* performs — inviting and removing their own users, which is story 2
and the thing they do repeatedly. Onboarding happens once per customer and is
performed by us.

**Consequences, stated so they are not surprises.**

- Onboarding needs shell access. There is no self-serve signup, and UAT 1
  (#52) records the command it ran rather than a portal walk-through.
- The audit row for a new tenant's first admin names `system` as the actor,
  because the CLI binds no user. `app/delivery/__main__.py` already made this
  trade and the reasoning is the same: "a human at a console did this, and we
  cannot say which human" beats silence.
- The first admin's password is printed to a terminal. It exists nowhere else,
  and the operator is expected to pass it on and let the customer change it.
  Lacking any mail path, the alternatives were worse: a password we choose for
  them and keep, or an account with no way in.

**Revisit when** a platform-operator role exists for some other reason, or when
self-serve signup becomes a product requirement. At that point this becomes a
route behind that role, and `accounts.create_tenant` is already the function it
would call — the module boundary was drawn so that the decision is only about
the surface.
