import { Component, signal } from '@angular/core';
import { MapComponent } from './map/map';
import { Dashboard } from './dashboard/dashboard';

@Component({
  selector: 'app-root',
  imports: [MapComponent, Dashboard],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('smart-city-twin');
}
