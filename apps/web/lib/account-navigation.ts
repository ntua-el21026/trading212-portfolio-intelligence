/** Replace the document so prior account server payloads cannot survive navigation. */
export function navigateAccountDocument(href: string): void {
  window.location.assign(href);
}
