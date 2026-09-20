/**
 * components/appHeader.js — shared header, reused by every view.
 *
 * Markup and the brand logo are copied verbatim from legacy files/Index.html
 * (the .app-header/.brand/.header-meta block) so the header reads identically
 * to the legacy app once the Daily Allocation/Reports/Audit views are ported
 * alongside it (CLAUDE.md section 7, "UI fidelity").
 */

const LOGO_SRC = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAABYCAMAAACQ7hpjAAAAYFBMVEXbslPr3ditYRrn0Z3MoZjKkiavaFrBfAbkw3KTMR27g3a+gCB+BwC/jYGPJBD+/f2JGQTPlhGYOii7dQbWpjPjyIzHiAvRq6QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA5mgU6AAAAGHRSTlP////////////////////////////////gEcFnAAAELUlEQVR42q2ZbZujKgyGDSJq5xyK1tL//0838QVDACuzyzWfZtt7nzwhITBNszTN0j6fTwD90f8/DC41z6O1dpy/Lavwe8N7GN5NN03LRJywAJfWGnHW0bLl5ebns22GBn8W5HQRhxN1Y2ZbRjFOh2sqcHaaNmMBFTgUF4IuORsqq4o4MAwD6bmIK0bNKWnVg3JWPdOXuMJCUjaugzPd5DzhISQFzrD6429y8EuxJJ4vfzuuVZJyOT0Ncda4gDbyo9G4qXEf3gTxuHaO/s+FZe1sjNbwFbRyuobH9YkDX3HK5FhwenToWZoCJ9Cs0Sko5ZAeX+RsrLmRorSr5xDJPgTJuEy+vnHo8zaODnL++OkrB7+hIkkPd3KWjdPf4qCkTyroyPuup7vBwS/pRNCmZ6mIS4KAxYVri8u/b3Ei0Joyrufl/V2OdafZHyd8ruLMEAXG4/IVHOtMFNivOSyyh5M+V3EML7Ldn6XWH1rADOJ6kPOq4LhHifPyfQ1HHYFhO9vqYlmmes4ZmNo5U+BU+RM2tYr0/CDnVcUxeT19LUcJDtrcEafvqzh2hNjnLV8vWlWc3eiQ9y0uwqgqjmvD6cM4qlrPnrBQFzSw/AXHnHo64qjquPSRroSTOd+/cc4+hnPzzknj0qoMcp9wNgufZVz4P4Jx13qU4HQpZ9v5ZRCEmePIl9/1CH8gnirEWnu9CZw35X2hOhV6QkFr60p1ys7lndO9+phD/3a0vNEVGqJxCUfmKzp9M2mjsgAX6/HEUSIuyI6CUdtQnOPXuiAO18NOumzOSG481015js7MgfHJDNHcu/vzEnUxQjK9yc2sonmV4kJ/RL3zsHJRmejXQU+HnJ7rcc1lVDglanEvOPIV70Nmj3I5c7S8p7w3n39EXUBZjlQTcWT/gZI7TngT5X0hTs/ims8tKK8HOt3erN67SM9ZXOCi+4paW1L2frpxXqpnek7OYQRdoGa8P4GxLnvv3usi7j8nZ5/81xvdR5s527GjvoGrTf3ZHZ2VUrN1F+8J7+Az54R8mTOu63cSxuF9A8pFcc0p7Of7HB/8+Recn9jnUO/6Fxzuz9F/fsVp034Its7nTnJMsW1897nNnBf6Jqf1Z97bzPkFN+Ni81jMUfczz/SQz332fIdqnwXn9haaQ/9ZOXIOd59bkblZxXp6Of8cezFzvEdn2cg4PtVzRpYdXMKHUC6bo/rMnHle+oqKnAHpc+aeEsq+NG+iZOMu+mr6BJGb7ug96LgXHHXRb3pkks+BAcQbLXZaA+ccHji9Jz3JZmEvR4Bj+fqA57ZTCGiTOrEP93tc5jjnj1mg6bV9Vka3LJF8riM97/zmxbM4/xZ5eMbi8hccuwch3w+NS/uPp7jaYjHR0R6/+rXsgOY+e7+9A9jiHxfsiK7QXxFgfWBnHxwV+Uz3lD/TRVKi2rROvAAAAABJRU5ErkJggg==';

/**
 * @param {{ user?: { display_name: string, email: string, role: 'admin' | 'operator' } }} [opts]
 */
export function renderAppHeader(opts = {}) {
  const user = opts.user || null;

  const metaHtml = user
    ? `
      <div class="header-meta">
        <div class="header-meta__item header-meta__item--user">
          <span class="header-meta__value" title="${escapeHtml(user.email)}">${escapeHtml(user.display_name)}</span>
          <!-- LEGACY INCONSISTENCY, resolved towards the stylesheet. Audit.html
               writes 'role-pill--user' but StylesAudit.html only ever defines
               'role-pill--operator', so in legacy the non-admin pill is
               unstyled. The stylesheet is the visual contract, so the modifier
               it declares is the one used here. Raised, not silently ported. -->
          <span class="role-pill ${
            user.role === 'admin' ? 'role-pill--admin' : 'role-pill--operator'
          }">
            ${user.role === 'admin' ? 'Admin' : 'Operator'}
          </span>
        </div>
        <button type="button" class="btn btn--tiny" id="signOutBtn">Sign out</button>
      </div>`
    : '';

  return `
    <header class="app-header" role="banner">
      <div class="app-header__inner">
        <div class="brand">
          <img class="brand__logo" alt="Royal Chain logo" src="${LOGO_SRC}">
          <div class="brand__text">
            <div class="brand__title">Royal Metal Allocation System</div>
          </div>
        </div>
        ${metaHtml}
      </div>
    </header>
  `;
}

export function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}
