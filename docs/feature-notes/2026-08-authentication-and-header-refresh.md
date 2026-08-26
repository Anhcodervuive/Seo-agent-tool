# Authentication and Header Experience Refresh

**Completed:** 25 August 2026
**Responsive hardening:** 26 August 2026

## Purpose

The shared application header and sign-in screen were redesigned to match the
quality of the Trends and Keyword Research workspaces. The authentication,
authorization, and redirect behavior are unchanged.

## User-facing result

### Sign-in screen

- The page now explains the workspace clearly without overwhelming the form.
- Login errors appear inside the sign-in card, close to the affected action.
- Username and password fields use browser autocomplete correctly.
- Users can show or hide the password before submitting.
- The submit button shows a busy state while the request is being processed.
- The layout adapts from a two-column desktop presentation to a focused mobile
  sign-in card.
- Dark, light, and device theme preferences remain available before login.

### Shared header

- The product identity, primary navigation, and account actions are separated
  into clear visual groups.
- The current primary feature is highlighted in the navigation.
- Theme selection is compact and keeps the existing System, Dark, and Light
  behavior.
- Username, role, project access, Admin Settings, and Sign Out are grouped into
  one account menu.
- Admin Settings is rendered only for administrators.
- Tablet and mobile users receive a collapsible navigation menu without
  horizontal page overflow.

### Responsive hardening

- Authenticated desktop navigation now stays grouped on the right while the
  product identity remains anchored on the left.
- Login field padding is scoped above the shared form styles, preventing field
  icons from overlapping typed values.
- Short desktop viewports can scroll vertically instead of clipping login
  content, and the username field no longer forces the page to auto-scroll on
  initial load.
- Theme options now have explicit dark and light popup colours for readable
  native dropdowns on Windows.

## Existing behavior intentionally preserved

- `POST /login` still accepts the existing `username` and `password` fields.
- Successful login still redirects to the Projects page.
- Invalid credentials still return the same safe generic error.
- The existing Flask-Login session and role checks remain the source of truth.
- Logout and all protected route behavior are unchanged.
- No database migration or data backfill is required.

## Support notes

- If the header looks stale after deployment, perform a hard refresh so the
  browser reloads the updated template and stylesheet.
- The account menu is deliberately the only place for Admin Settings and Sign
  Out; this prevents the desktop header from becoming crowded.
- On mobile, open the menu button first to access feature navigation, theme,
  and account controls.

## Verification

Automated checks cover:

- the public sign-in layout and accessible form attributes;
- invalid credential feedback;
- the existing successful-login redirect;
- administrator-only navigation;
- member account navigation and hidden administrator controls.

Browser verification covers dark and light modes at desktop width, tablet
width, and a 390-pixel mobile viewport. It also covers active navigation,
mobile menu expansion, account menu expansion, password visibility, and the
invalid-login state.

## Main implementation files

- `pipeline/app/templates/base.html`
- `pipeline/app/templates/login.html`
- `pipeline/app/static/css/style.css`
- `pipeline/tests/test_auth_ui.py`

## Delivery

The implementation is ready for the next repository commit after final review.
