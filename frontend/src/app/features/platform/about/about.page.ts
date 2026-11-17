import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

/** WaitLess About Us (PRD §2.1). Becomes Super Admin editable content in Phase 11. */
@Component({
  selector: 'wl-about-page',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-page wl-container about">
      <p class="wl-eyebrow">About WaitLess</p>
      <h1 class="wl-h2">Less waiting. <span class="wl-script">More dining.</span></h1>
      <p class="lead">
        WaitLess helps restaurants digitise their operations and helps guests avoid unnecessary waiting — from finding
        a table to the moment the bill is paid.
      </p>

      <div class="pair">
        <article class="wl-card">
          <h2>Our vision</h2>
          <p>Every meal out should start on time. No guessing at the door, no wondering where the food is.</p>
        </article>
        <article class="wl-card">
          <h2>Our mission</h2>
          <p>Give every restaurant — from a single café to a chain — its own branded app and the tools to serve faster.</p>
        </article>
      </div>

      <h2 class="h3">How WaitLess works</h2>
      <ol class="flow">
        <li><b>Discover</b> restaurants and see who is open right now.</li>
        <li><b>Book or queue</b> from your phone — or scan the QR code at the entrance.</li>
        <li><b>Order</b> from the restaurant's digital menu; with a paid booking you can pre-order.</li>
        <li><b>15-minute promise</b>: the serving timer starts when your order is accepted. Late? Your discount grows 2% every 5 minutes.</li>
        <li><b>Pay</b> the final bill — discounts already applied.</li>
      </ol>

      <div class="pair">
        <article class="wl-card">
          <h2>For guests</h2>
          <ul>
            <li>No standing in line — live queue position on your phone</li>
            <li>Reserve tables and pre-order</li>
            <li>Food on time, or automatically cheaper</li>
            <li>Clear bills with every discount shown</li>
          </ul>
        </article>
        <article class="wl-card">
          <h2>For restaurants</h2>
          <ul>
            <li>Your own branded storefront and digital menu</li>
            <li>Queue, tables, reservations and kitchen in one place</li>
            <li>Inventory, billing, POS and analytics</li>
            <li>Approve, publish and grow at your own pace</li>
          </ul>
        </article>
      </div>

      <div class="cta">
        <a routerLink="/restaurants" class="wl-btn wl-btn--primary">Find a restaurant</a>
        <a routerLink="/register-restaurant" class="wl-btn wl-btn--ghost">Register your restaurant</a>
      </div>
    </section>
  `,
  styles: `
    .about {
      max-width: 960px;
    }
    .lead {
      font-size: 1.1rem;
      color: var(--wl-text-soft);
      max-width: 60ch;
    }
    .pair {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin: 1.6rem 0;
      h2 {
        font: 600 1.4rem var(--wl-font-serif);
        margin-bottom: 0.4rem;
      }
      ul {
        display: grid;
        gap: 0.35rem;
        padding-left: 1.1rem;
        list-style: disc;
      }
    }
    .h3 {
      font: 600 1.7rem var(--wl-font-serif);
      margin-top: 2rem;
    }
    .flow {
      display: grid;
      gap: 0.6rem;
      margin-top: 0.8rem;
      padding-left: 1.3rem;
      list-style: decimal;
    }
    .cta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.7rem;
      margin-top: 2rem;
    }
    @media (max-width: 700px) {
      .pair {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class AboutPage {}
