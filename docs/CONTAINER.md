# Building and Running with Sysbox

This guide covers the steps to build and run a container using the Sysbox runtime. Sysbox is a secure container runtime that enables system-level containers (e.g., systemd, Docker-in-Docker) to run inside unprivileged containers.

## Prerequisites

- **Docker** (version 19.03 or later) installed on your host.
- **Sysbox** must be installed and configured.

After installing Sysbox, you need to integrate it with Docker by adding the runtime to Docker's daemon configuration.

### Docker Daemon Configuration

Edit the Docker daemon configuration file (`/etc/docker/daemon.json`) and add the Sysbox runtime entry:

```json
{
  "runtimes": {
    "sysbox-runc": {
      "path": "/usr/bin/sysbox-runc"
    }
  }
}
```

Then restart the Docker daemon for the changes to take effect:

```bash
sudo systemctl restart docker
```

Verify that Sysbox is registered correctly:

```bash
docker info | grep -A 5 Runtimes
```

You should see `sysbox-runc` listed among the available runtimes.

## Building the Container Image

Build your Docker image as usual. Replace `<image-name>` with your desired image name and tag.

```bash
docker build -t <image-name> .
```

## Running the Container with Sysbox

To start a container using the Sysbox runtime, use the `--runtime` flag with `docker run`:

```bash
docker run --runtime=sysbox-runc <image-name>
```

You can also add any other Docker options (ports, volumes, environment variables, etc.) as needed.

> **Note:** The Sysbox runtime provides isolation and allows system-level workloads inside the container. It does not require privileged mode (`--privileged`), making it more secure than traditional system containers.

## CI/CD Integration

Integration with CI/CD pipelines is currently **under development**. We plan to provide:
- GitLab CI templates
- Jenkins pipeline examples

## Further Reading

- [Sysbox GitHub Repository](https://github.com/nestybox/sysbox)
- [Docker Documentation](https://docs.docker.com/)
