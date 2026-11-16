import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import { Branch } from '../tenancy/tenancy.models';
import {
  BranchLocation,
  Branding,
  BrandingUpdate,
  Gallery,
  Hours,
  HoursDay,
  Profile,
  ProfileUpdate,
  PublishChecklist,
  SocialLink,
} from './restaurant.models';

/** Restaurant admin: profile, branding, gallery, hours, social links, publishing (PRD §5). */
@Injectable({ providedIn: 'root' })
export class RestaurantService {
  private readonly api = inject(ApiService);

  profile(): Observable<Profile> {
    return this.api.get('restaurant/profile');
  }
  updateProfile(body: ProfileUpdate): Observable<Profile> {
    return this.api.put('restaurant/profile', body);
  }

  branding(): Observable<Branding> {
    return this.api.get('restaurant/branding');
  }
  updateBranding(body: BrandingUpdate): Observable<Branding> {
    return this.api.put('restaurant/branding', body);
  }
  resetBranding(): Observable<Branding> {
    return this.api.post('restaurant/branding/reset', {});
  }
  uploadLogo(file: File): Observable<Branding> {
    return this.api.post('restaurant/branding/logo', formData(file));
  }
  removeLogo(): Observable<Branding> {
    return this.api.delete('restaurant/branding/logo');
  }
  uploadCover(file: File): Observable<Profile> {
    return this.api.post('restaurant/branding/cover', formData(file));
  }
  removeCover(): Observable<Profile> {
    return this.api.delete('restaurant/branding/cover');
  }

  gallery(): Observable<Gallery> {
    return this.api.get('restaurant/gallery');
  }
  addPhoto(file: File, caption = ''): Observable<Gallery> {
    const fd = formData(file);
    fd.append('caption', caption);
    return this.api.post('restaurant/gallery', fd);
  }
  replacePhoto(id: string, file: File): Observable<Gallery> {
    return this.api.put(`restaurant/gallery/${id}`, formData(file));
  }
  captionPhoto(id: string, caption: string): Observable<Gallery> {
    return this.api.patch(`restaurant/gallery/${id}`, { caption });
  }
  deletePhoto(id: string): Observable<Gallery> {
    return this.api.delete(`restaurant/gallery/${id}`);
  }
  reorderPhotos(ids: string[]): Observable<Gallery> {
    return this.api.put('restaurant/gallery/order', { ids });
  }

  updateBranch(id: string, body: BranchLocation): Observable<Branch> {
    return this.api.patch(`restaurant/branches/${id}`, body);
  }
  hours(branchId: string): Observable<Hours> {
    return this.api.get(`restaurant/branches/${branchId}/hours`);
  }
  setHours(branchId: string, days: HoursDay[]): Observable<Hours> {
    return this.api.put(`restaurant/branches/${branchId}/hours`, { days });
  }

  socialLinks(): Observable<SocialLink[]> {
    return this.api.get('restaurant/social-links');
  }
  setSocialLinks(links: SocialLink[]): Observable<SocialLink[]> {
    return this.api.put('restaurant/social-links', { links });
  }

  checklist(): Observable<PublishChecklist> {
    return this.api.get('restaurant/publish-checklist');
  }
  publish(published: boolean): Observable<PublishChecklist> {
    return this.api.post('restaurant/publish', { published });
  }
}

function formData(file: File): FormData {
  const fd = new FormData();
  fd.append('file', file, file.name);
  return fd;
}
