const MENU_TEXT_ID = "isittrue-check-text";
const MENU_IMAGE_ID = "isittrue-check-image";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_TEXT_ID,
    title: "Check this text with IsItTrue",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: MENU_IMAGE_ID,
    title: "Check this image with IsItTrue",
    contexts: ["image"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  let payload;

  if (info.menuItemId === MENU_TEXT_ID) {
    payload = { type: "text", text: info.selectionText || "" };
  } else if (info.menuItemId === MENU_IMAGE_ID) {
    payload = { type: "image", srcUrl: info.srcUrl };
  } else {
    return;
  }

  // Handed off via session storage (not the URL) so an image's srcUrl or a
  // long selection never has to be crammed into a query string.
  const id = crypto.randomUUID();
  await chrome.storage.session.set({ [id]: payload });
  chrome.tabs.create({ url: chrome.runtime.getURL(`results.html?id=${id}`) });
});
