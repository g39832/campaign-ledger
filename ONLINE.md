# Playing online with friends anywhere (free)

Campaign Ledger runs on **your** computer. To play with people who aren't on your
Wi-Fi, they need a way to reach it. Here are the free ways, easiest first, and
what to expect from each. None of them cost anything.

## Option 1 — "Go online" button (recommended)

Uses a free **Cloudflare quick tunnel**. You get a public `https://….trycloudflare.com`
link that leads to your app. No account, no domain, and no changes to your router.

**One-time setup** (about a minute):

1. Open **PowerShell** and run:

   ```
   winget install --id Cloudflare.cloudflared
   ```

2. Close the app window and start it again (`start.bat` is enough; LAN mode isn't needed for this).

**Every game night:**

1. Start the app and open **Players**.
2. Click **Go online**. After a few seconds you see a link like
   `https://quiet-river-1234.trycloudflare.com/join`.
3. Click **Copy link + code** and send it to your group (Discord, text, whatever).
4. Friends open the link, type their name, pick their character and play.
5. When you're done, click **Stop**, or just close the app.

**Good to know:**

* **The link is new every time** you click Go online. Send the new one each session.
* **It only works while your computer is on and the app is running.** Your data
  stays on your computer the whole time.
* **Anyone with the link reaches the join page, and nothing more.** To get in they
  still need the join code. Click **New code** whenever you like; people already
  in stay in.
* **Nobody coming through the link is ever treated as the DM.** The app checks for
  Cloudflare's headers, which a visitor can't remove.
* **Wrong-code guessing is limited per visitor.** Someone guessing codes can't lock
  your friends out.
* **You can still run the game from your tablet.** Make a DM link on the Players page
  and open it through the online link. Treat a DM link like a password.
* **Speed:** the app syncs every 1.5 seconds. That's plenty for 5–6 players on normal
  home internet.

## Option 2 — Tailscale (private network)

Tailscale is free for personal use. It makes a private network between your
devices and any friends you invite. Nothing is exposed to the public internet.

1. Install Tailscale on your PC (it's already installed on this one) and sign in.
2. In the Tailscale admin page, use **Share** on this computer and send the invite
   to each friend. They install Tailscale and accept it.
3. Start the app with `start-lan.bat`.
4. Friends open `http://<your Tailscale IP>:5050/join` (it starts with 100., and the
   Players page lists it as "Tailscale").

This is best for a regular group that doesn't mind installing one app. The
address never changes.

## Option 3 — run it on the Raspberry Pi (always on)

The Pi uses less power than leaving your PC on.

1. Copy the app to the Pi.
2. Run it there with `--lan`.
3. Use Option 1 or 2 on the Pi itself.

Your PC can be off while friends check the map or their sheets between sessions.
This needs a little Linux setup, so ask when you want to do it.

## What players get

* **The shared map, live:**
  * spell areas
  * pings, by double-tapping or using the Ping tool
  * a measure tool
  * moving their own token, if you allow it
* **Their own character:** HP, rolls, attacks and spells.
* **Turn order**, with a "Your turn!" banner and sound.
* **Dice rolls** as they happen.

## Ideas to make online play better later (still free)

* **Instant updates instead of a 1.5 s poll:** server-sent events would make moves
  and pings show up right away.
* **Voice:** use a free Discord call alongside the app. A shared screen isn't
  needed, since everyone has their own map.
* **Player handouts:** the DM pushes an image or note to everyone's screen.
* **A fixed address:** a Cloudflare *named* tunnel keeps the same address every
  time, but it needs a domain name (about $10 a year). That isn't free, so it's left
  out on purpose.
