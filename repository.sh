#!/usr/bin/env bash

set -euo pipefail

workspace_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state_dir="${workspace_root}/.pypi-repository"
container_name="engulf-package-repository"
image_name="engulf-package-repository:local"
owner_label="org.engulf.package-repository=managed"
hosts_marker="# engulf-package-repository"

usage() {
    cat >&2 <<EOF
usage:
  $0 start --cert PATH --key PATH [--ca-cert PATH] [--hostname FQDN]
      [--storage DIRECTORY] [--public]
  $0 destroy
  $0 status
  $0 logs
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

container_exists() {
    docker container inspect "${container_name}" >/dev/null 2>&1
}

container_is_owned() {
    [[ $(docker container inspect --format '{{ index .Config.Labels "org.engulf.package-repository" }}' "${container_name}" 2>/dev/null) == managed ]]
}

pip_get_user() {
    python3 -m pip config --user get "$1" 2>/dev/null || true
}

value_contains_line() {
    local value=$1
    local expected=$2
    while IFS= read -r line; do
        [[ $line == "${expected}" ]] && return 0
    done <<<"${value}"
    return 1
}

remove_value_line() {
    local value=$1
    local unwanted=$2
    while IFS= read -r line; do
        [[ -z $line || $line == "${unwanted}" ]] || printf '%s\n' "${line}"
    done <<<"${value}"
}

add_pip_configuration() {
    local repository_url=$1
    local simple_url="${repository_url%/}/simple/"
    local current
    local updated

    current=$(pip_get_user global.extra-index-url)
    if ! value_contains_line "${current}" "${simple_url}"; then
        if [[ -n $current ]]; then
            updated="${current}"$'\n'"${simple_url}"
        else
            updated="${simple_url}"
        fi
        python3 -m pip config --user set global.extra-index-url "${updated}" >/dev/null
        printf '%s\n' "${simple_url}" >"${state_dir}/pip-index-added"
    fi

    if ! openssl verify -CAfile "${state_dir}/system-ca.pem" "${state_dir}/certificate.pem" >/dev/null 2>&1; then
        local previous_cert
        previous_cert=$(pip_get_user global.cert)
        if [[ -n $previous_cert ]]; then
            printf '%s\n' "${previous_cert}" >"${state_dir}/pip-cert-previous"
            : >"${state_dir}/pip-cert-previous-existed"
        fi
        python3 -m pip config --user set global.cert "${state_dir}/client-ca.pem" >/dev/null
        : >"${state_dir}/pip-cert-added"
    fi
}

remove_pip_configuration() {
    if [[ -f ${state_dir}/pip-index-added ]]; then
        local added_url
        local current
        local remaining
        added_url=$(<"${state_dir}/pip-index-added")
        current=$(pip_get_user global.extra-index-url)
        remaining=$(remove_value_line "${current}" "${added_url}")
        if [[ -n $remaining ]]; then
            python3 -m pip config --user set global.extra-index-url "${remaining}" >/dev/null
        else
            python3 -m pip config --user unset global.extra-index-url >/dev/null 2>&1 || true
        fi
        rm -f -- "${state_dir}/pip-index-added"
    fi

    if [[ -f ${state_dir}/pip-cert-added ]]; then
        local current_cert
        current_cert=$(pip_get_user global.cert)
        if [[ $current_cert == "${state_dir}/client-ca.pem" ]]; then
            if [[ -f ${state_dir}/pip-cert-previous-existed ]]; then
                python3 -m pip config --user set global.cert "$(<"${state_dir}/pip-cert-previous")" >/dev/null
            else
                python3 -m pip config --user unset global.cert >/dev/null 2>&1 || true
            fi
        else
            echo "warning: pip global.cert changed after launch; leaving it untouched" >&2
        fi
        rm -f -- \
            "${state_dir}/pip-cert-added" \
            "${state_dir}/pip-cert-previous" \
            "${state_dir}/pip-cert-previous-existed"
    fi
}

add_hosts_entry() {
    local hostname=$1
    if getent ahostsv4 "${hostname}" >/dev/null 2>&1; then
        return
    fi
    echo "Adding ${hostname} to /etc/hosts (sudo may prompt)."
    printf '127.0.0.1\t%s\t%s\n' "${hostname}" "${hosts_marker}" | sudo tee -a /etc/hosts >/dev/null
    printf '%s\n' "${hostname}" >"${state_dir}/hosts-entry-added"
}

remove_hosts_entry() {
    [[ -f ${state_dir}/hosts-entry-added ]] || return 0
    local temporary
    temporary=$(mktemp)
    awk -v marker="${hosts_marker}" 'index($0, marker) == 0' /etc/hosts >"${temporary}"
    echo "Removing the managed package-repository entry from /etc/hosts (sudo may prompt)."
    if ! sudo cp -- "${temporary}" /etc/hosts; then
        rm -f -- "${temporary}"
        return 1
    fi
    rm -f -- "${temporary}" "${state_dir}/hosts-entry-added"
}

cleanup_client_configuration() {
    local failure=0
    remove_pip_configuration || failure=1
    remove_hosts_entry || failure=1
    if (( failure )); then
        echo "warning: client configuration cleanup was incomplete; retry destroy" >&2
        return 1
    fi
    rm -f -- "${state_dir}/active"
}

reconcile_stale_state() {
    if [[ -f ${state_dir}/active ]] && ! container_exists; then
        echo "Reconciling client configuration left by a removed container."
        cleanup_client_configuration
    fi
}

find_system_ca_bundle() {
    local candidate
    for candidate in \
        /etc/ssl/certs/ca-certificates.crt \
        /etc/pki/tls/certs/ca-bundle.crt \
        /etc/ssl/ca-bundle.pem; do
        if [[ -r $candidate ]]; then
            printf '%s\n' "${candidate}"
            return
        fi
    done
    die "could not locate the system CA bundle"
}

create_authentication() {
    if [[ ! -f ${state_dir}/upload-token ]]; then
        umask 077
        openssl rand -hex 32 >"${state_dir}/upload-token"
    fi
    docker run --rm -i --entrypoint python "${image_name}" -c \
        'import sys; from passlib.apache import HtpasswdFile; f=HtpasswdFile(default_scheme="bcrypt"); f.set_password("__token__", sys.stdin.read().strip()); sys.stdout.buffer.write(f.to_string())' \
        <"${state_dir}/upload-token" >"${state_dir}/htpasswd"
    chmod 0600 "${state_dir}/upload-token" "${state_dir}/htpasswd"
}

start_repository() {
    local certificate=""
    local private_key=""
    local ca_certificate=""
    local requested_hostname=""
    local requested_storage=""
    local public=false
    while (( $# )); do
        case "$1" in
            --cert)
                (( $# >= 2 )) || die "--cert requires a path"
                certificate=$2
                shift 2
                ;;
            --key)
                (( $# >= 2 )) || die "--key requires a path"
                private_key=$2
                shift 2
                ;;
            --ca-cert)
                (( $# >= 2 )) || die "--ca-cert requires a path"
                ca_certificate=$2
                shift 2
                ;;
            --hostname)
                (( $# >= 2 )) || die "--hostname requires an FQDN"
                requested_hostname=$2
                shift 2
                ;;
            --storage)
                (( $# >= 2 )) || die "--storage requires a directory"
                requested_storage=$2
                shift 2
                ;;
            --public)
                public=true
                shift
                ;;
            *) die "unknown start option: $1" ;;
        esac
    done
    [[ -n $certificate ]] || die "--cert is required"
    [[ -n $private_key ]] || die "--key is required"
    local packages_directory="${state_dir}/packages"
    if [[ -n $requested_storage ]]; then
        [[ $requested_storage != *$'\n'* ]] || die "--storage cannot contain a newline"
        [[ -d $requested_storage ]] || \
            die "storage directory does not exist: ${requested_storage}"
        packages_directory=$(readlink -f -- "${requested_storage}")
        [[ -r $packages_directory && -w $packages_directory && -x $packages_directory ]] || \
            die "storage directory must be readable, writable, and searchable: ${packages_directory}"
    fi
    if [[ -n $ca_certificate ]]; then
        [[ -f $ca_certificate ]] || die "CA certificate does not exist: ${ca_certificate}"
        openssl verify -CAfile "${ca_certificate}" "${certificate}" >/dev/null || \
            die "server certificate is not trusted by --ca-cert"
    fi

    local certificate_arguments=(--cert "${certificate}" --key "${private_key}")
    if [[ -n $requested_hostname ]]; then
        certificate_arguments+=(--hostname "${requested_hostname}")
    fi
    local hostname
    hostname=$(python3 "${workspace_root}/repository/certificate.py" "${certificate_arguments[@]}" --field hostname)
    mapfile -t san_addresses < <(
        python3 "${workspace_root}/repository/certificate.py" "${certificate_arguments[@]}" --field ipv4
    )

    if container_exists; then
        container_is_owned || die "container ${container_name} exists but is not managed by this launcher"
        die "repository is already running; destroy it before changing its configuration"
    fi

    local started=false
    rollback_start() {
        if [[ $started != true ]]; then
            if container_exists && container_is_owned; then
                docker rm --force "${container_name}" >/dev/null 2>&1 || true
            fi
            cleanup_client_configuration || true
        fi
    }
    trap rollback_start EXIT

    certificate=$(readlink -f -- "${certificate}")
    private_key=$(readlink -f -- "${private_key}")
    if [[ -n $ca_certificate ]]; then
        ca_certificate=$(readlink -f -- "${ca_certificate}")
    fi
    local system_ca
    system_ca=$(find_system_ca_bundle)
    if [[ -n $ca_certificate ]]; then
        cat -- "${certificate}" "${ca_certificate}" >"${state_dir}/certificate.pem"
        cp -- "${ca_certificate}" "${state_dir}/repository-ca.pem"
    else
        cp -- "${certificate}" "${state_dir}/certificate.pem"
        cp -- "${certificate}" "${state_dir}/repository-ca.pem"
    fi
    cp -- "${private_key}" "${state_dir}/private-key.pem"
    cp -- "${system_ca}" "${state_dir}/system-ca.pem"
    cat -- "${system_ca}" "${state_dir}/repository-ca.pem" >"${state_dir}/client-ca.pem"
    chmod 0600 "${state_dir}/private-key.pem"
    chmod 0644 \
        "${state_dir}/certificate.pem" \
        "${state_dir}/client-ca.pem" \
        "${state_dir}/repository-ca.pem" \
        "${state_dir}/system-ca.pem"

    docker build \
        --tag "${image_name}" \
        --file "${workspace_root}/repository/Dockerfile" \
        "${workspace_root}"
    create_authentication
    add_hosts_entry "${hostname}"

    local published_port="127.0.0.1:443:8080"
    if [[ $public == true ]]; then
        published_port="0.0.0.0:443:8080"
    fi
    local repository_url="https://${hostname}/"
    printf '%s\n' "${hostname}" >"${state_dir}/hostname"
    printf '%s\n' "${repository_url}" >"${state_dir}/repository-url"
    printf '%s\n' "${packages_directory}" >"${state_dir}/packages-directory"
    printf '%s\n' "${public}" >"${state_dir}/public"
    : >"${state_dir}/active"

    docker run --detach \
        --name "${container_name}" \
        --label "${owner_label}" \
        --hostname "${hostname}" \
        --restart unless-stopped \
        --user "$(id -u):$(id -g)" \
        --publish "${published_port}" \
        --volume "${packages_directory}:/data/packages" \
        --volume "${state_dir}/package-docs:/data/package-docs" \
        --volume "${state_dir}/htpasswd:/data/auth/htpasswd:ro" \
        --volume "${state_dir}/certificate.pem:/data/tls/certificate.pem:ro" \
        --volume "${state_dir}/private-key.pem:/data/tls/private-key.pem:ro" \
        --entrypoint gunicorn \
        "${image_name}" \
        --chdir /data --config /data/gunicorn.conf.py \
        repository_app:application >/dev/null

    local healthy=false
    local attempt
    for attempt in {1..30}; do
        if curl --silent --show-error --fail --noproxy '*' \
            --cacert "${state_dir}/client-ca.pem" \
            --resolve "${hostname}:443:127.0.0.1" \
            "${repository_url}health" >/dev/null 2>&1; then
            healthy=true
            break
        fi
        sleep 0.5
    done
    if [[ $healthy != true ]]; then
        docker logs "${container_name}" >&2 || true
        die "repository did not become healthy"
    fi

    if ! curl --silent --show-error --fail --noproxy '*' \
        --cacert "${state_dir}/client-ca.pem" \
        "${repository_url}health" >/dev/null; then
        die "${hostname} does not resolve back to this repository on the host"
    fi

    add_pip_configuration "${repository_url}"
    started=true
    trap - EXIT

    echo "Repository: ${repository_url}"
    echo "Simple index: ${repository_url}simple/"
    echo "Documentation: ${repository_url}docs/"
    echo "Package storage: ${packages_directory}"
    echo "Upload URL: ${repository_url}"
    echo "Set TWINE_REPOSITORY_URL=${repository_url} before running ./publish.sh."
    if [[ $public == true && ${#san_addresses[@]} -gt 0 ]]; then
        echo "Certificate IPv4 SAN URLs for remote clients:"
        local address
        for address in "${san_addresses[@]}"; do
            [[ -n $address ]] && echo "  https://${address}/simple/"
        done
    fi
}

destroy_repository() {
    if container_exists; then
        container_is_owned || die "container ${container_name} is not managed by this launcher"
        docker rm --force "${container_name}" >/dev/null
    fi
    cleanup_client_configuration
    echo "Repository container and launcher-owned client configuration removed."
    if [[ -f ${state_dir}/packages-directory ]]; then
        echo "Packages remain in $(<"${state_dir}/packages-directory")."
    fi
    echo "Upload credentials remain in ${state_dir}."
}

status_repository() {
    if container_exists; then
        container_is_owned || die "container ${container_name} is not managed by this launcher"
        docker container inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "${container_name}"
        [[ -f ${state_dir}/repository-url ]] && echo "repository=$(<"${state_dir}/repository-url")"
        [[ -f ${state_dir}/packages-directory ]] && echo "storage=$(<"${state_dir}/packages-directory")"
    else
        echo "status=stopped"
    fi
    return 0
}

main() {
    (( $# >= 1 )) || { usage; exit 2; }
    require_command docker
    require_command flock
    require_command openssl
    require_command python3
    require_command curl
    require_command getent
    require_command sudo
    docker info >/dev/null 2>&1 || die "Docker Engine is not available to the current user"

    [[ -z ${PIP_CONFIG_FILE:-} ]] || echo "warning: PIP_CONFIG_FILE overrides normal pip configuration loading" >&2
    [[ -z ${PIP_EXTRA_INDEX_URL:-} ]] || echo "warning: PIP_EXTRA_INDEX_URL overrides pip's configured extra indexes" >&2
    [[ -z ${PIP_CERT:-} ]] || echo "warning: PIP_CERT overrides pip's configured certificate bundle" >&2

    mkdir -p -- "${state_dir}/packages" "${state_dir}/package-docs"
    chmod 0700 "${state_dir}"
    exec 9>"${state_dir}/launcher.lock"
    flock 9
    reconcile_stale_state

    local command=$1
    shift
    case "${command}" in
        start) start_repository "$@" ;;
        destroy)
            (( $# == 0 )) || die "destroy takes no arguments"
            destroy_repository
            ;;
        status)
            (( $# == 0 )) || die "status takes no arguments"
            status_repository
            ;;
        logs)
            (( $# == 0 )) || die "logs takes no arguments"
            container_exists || die "repository is not running"
            container_is_owned || die "container ${container_name} is not managed by this launcher"
            docker logs "${container_name}"
            ;;
        *) usage; exit 2 ;;
    esac
}

main "$@"
