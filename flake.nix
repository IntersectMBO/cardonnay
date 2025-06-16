{
  description = "Cardonnay - Cardano local testnets";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    cardano-node = {
      url = "github:IntersectMBO/cardano-node";
    };
    flake-utils = {
      url = "github:numtide/flake-utils";
    };
  };

  outputs = { self, nixpkgs, flake-utils, cardano-node }:
    flake-utils.lib.eachDefaultSystem
      (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          nodePkgs = cardano-node.packages.${system};
          py3Pkgs = pkgs.python311Packages;
          py3Full = pkgs.python311Full;
        in
        {
          devShells = rec {
            base = pkgs.mkShell {
              nativeBuildInputs = with pkgs; [ bash coreutils gnumake git jq ];
            };
            postgres = pkgs.mkShell {
              nativeBuildInputs = with pkgs; [ glibcLocales postgresql lsof procps ];
            };
            venv = pkgs.mkShell {
              nativeBuildInputs = base.nativeBuildInputs ++ postgres.nativeBuildInputs ++ [
                nodePkgs.cardano-cli
                nodePkgs.cardano-node
                nodePkgs.cardano-submit-api
                nodePkgs.bech32
                py3Full
                py3Pkgs.virtualenv
                py3Pkgs.pip
              ];
              shellHook = ''
                echo "Setting up environment..."
                [ -e .venv_nix ] || python3 -m venv .venv_nix
                source .venv_nix/bin/activate
                export PYTHONPATH=$(echo "$VIRTUAL_ENV"/lib/python3*/site-packages):"$PYTHONPATH"
                python3 -m pip install --require-virtualenv --upgrade -e .
                source completions/cardonnay.bash-completion
                echo "Environment ready."
              '';
            };
            # Use 'venv' directly as 'default'
            default = venv;
          };
        });

  # --- Flake Local Nix Configuration ----------------------------
  nixConfig = {
    # Sets the flake to use the IOG nix cache.
    extra-substituters = [ "https://cache.iog.io" ];
    extra-trusted-public-keys = [ "hydra.iohk.io:f/Ea+s+dFdN+3Y/G+FDgSq+a5NEWhJGzdjvKNGv0/EQ=" ];
    allow-import-from-derivation = "true";
  };
}
