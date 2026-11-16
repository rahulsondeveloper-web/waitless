import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTabsModule } from '@angular/material/tabs';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';

/**
 * Two ways in (decision D19):
 *  - Restaurant team & WaitLess admin: email or mobile + password
 *  - Customers: mobile + one-time code
 */
@Component({
  selector: 'wl-login-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatTabsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './login.page.html',
  styleUrl: './login.page.scss',
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(NonNullableFormBuilder);

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly otpSentTo = signal<string | null>(null);
  protected readonly devCode = signal<string | null>(null);

  protected readonly passwordForm = this.fb.group({
    identifier: ['', [Validators.required, Validators.minLength(3)]],
    password: ['', Validators.required],
  });

  protected readonly phoneForm = this.fb.group({
    phone: ['', [Validators.required, Validators.pattern(/^[+\d][\d\s-]{7,18}$/)]],
  });

  protected readonly codeForm = this.fb.group({
    code: ['', [Validators.required, Validators.pattern(/^\d{6}$/)]],
    fullName: [''],
  });

  protected submitPassword(): void {
    if (this.passwordForm.invalid) return this.passwordForm.markAllAsTouched();
    const { identifier, password } = this.passwordForm.getRawValue();
    this.run(this.auth.login(identifier, password), () => this.goHome());
  }

  protected sendCode(): void {
    if (this.phoneForm.invalid) return this.phoneForm.markAllAsTouched();
    this.run(this.auth.sendOtp(this.phoneForm.getRawValue().phone), (res) => {
      this.otpSentTo.set(res.phone);
      this.devCode.set(res.dev_code);
      this.codeForm.reset();
    });
  }

  protected verifyCode(): void {
    if (this.codeForm.invalid) return this.codeForm.markAllAsTouched();
    const { code, fullName } = this.codeForm.getRawValue();
    this.run(this.auth.verifyOtp(this.otpSentTo()!, code, fullName), () => this.goHome());
  }

  protected changeNumber(): void {
    this.otpSentTo.set(null);
    this.devCode.set(null);
    this.error.set(null);
  }

  private goHome(): void {
    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    const safe = returnUrl && returnUrl.startsWith('/') && !returnUrl.startsWith('//') ? returnUrl : null;
    void this.router.navigateByUrl(safe ?? this.auth.homeUrl());
  }

  private run<T>(obs: Observable<T>, onOk: (v: T) => void): void {
    this.busy.set(true);
    this.error.set(null);
    obs.subscribe({
      next: (v) => {
        this.busy.set(false);
        onOk(v);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(
          e.code === 'RATE_LIMITED'
            ? `Too many attempts. Try again in ${Math.ceil(Number(e.details['retry_after_seconds'] ?? 60) / 60)} min.`
            : e.message,
        );
      },
    });
  }
}
