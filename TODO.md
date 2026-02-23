# TO DO

- Remove devbox-connect. Instead, make it easy to copy an ssh tunnel command to expose all ports of all services to a remote box: `ssh -L 9000:localhost:9000 payne@dev.payne.io, etc.
- Add a scripts dir?

- tools: use std-in/std-out unix philosophy
- daemons or web-services: expose ports
- workers: just keep doing work in a background--usually watching the filesystem or a queue
- jobs: scheduled tools or daemon requests
- frontend: files served up by caddy
