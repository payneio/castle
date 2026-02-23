# TO DO

- Remove devbox-connect. Instead, make it easy to copy an ssh tunnel command to expose all ports of all services to a remote box: `ssh -L 9000:localhost:9000 payne@dev.payne.io, etc.
- Add a scripts dir?

- Component (software units) types:
  - python/golang/rust/bash tool: use std-in/std-out unix philosophy
  - python/golang/rust-daemon: Whatever
  - python web-service: RESTful, fastapi, SSE, etc.
  - react-frontend
  - python API

- Dependencies
  - docker/podman (mqtt)
  - all component system dependencies
  - uv
  - golang/rust/java/.net/whatever

- Add amplifier to make a component builder

-  What's this about? "I need to add the MQTT env vars to the systemd unit. Let me add them via a drop-in override so the deploy command doesn't overwrite them."
