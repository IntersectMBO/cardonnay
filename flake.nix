{
  description = "Cardonnay - Cardano local testnets";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    cardano-node = {
      url = "github:IntersectMBO/cardano-node";
    };
    # tx-centrifuge only, lives on a different cardano-node branch than the
    # one providing cardano-node / cardano-cli above.
    cardano-node-tx-centrifuge = {
      url = "github:IntersectMBO/cardano-node?ref=bench/leios-11.0.1";
    };
    # tx-firehose only, lives on yet another cardano-node branch.
    cardano-node-tx-firehose = {
      url = "github:IntersectMBO/cardano-node?ref=leios-prototype";
    };
    flake-utils = {
      url = "github:numtide/flake-utils";
    };
  };

  outputs = { self, nixpkgs, flake-utils, cardano-node, cardano-node-tx-centrifuge, cardano-node-tx-firehose }:
    flake-utils.lib.eachDefaultSystem
      (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          nodePkgs = cardano-node.packages.${system};
          centrifugePkgs = cardano-node-tx-centrifuge.packages.${system};
          firehosePkgs = cardano-node-tx-firehose.packages.${system};
          venvShellHook = ''
            echo "Setting up environment..."
            [ -e .nix_venv ] || python3 -m venv .nix_venv
            source .nix_venv/bin/activate
            export PYTHONPATH=$(echo "$VIRTUAL_ENV"/lib/python3*/site-packages):"$PYTHONPATH"
            python3 -m pip install --require-virtualenv --upgrade -e .
            source completions/cardonnay.bash-completion
            echo "Environment ready."
          '';
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
                nodePkgs.tx-generator
                pkgs.bashInteractive
                pkgs.python313
              ];
              shellHook = venvShellHook;
            };
            tx-centrifuge = pkgs.mkShell {
              nativeBuildInputs = venv.nativeBuildInputs ++ [
                centrifugePkgs.tx-centrifuge
              ];
              shellHook = venvShellHook;
            };
            tx-firehose = pkgs.mkShell {
              nativeBuildInputs = venv.nativeBuildInputs ++ [
                firehosePkgs.tx-firehose
              ];
              shellHook = venvShellHook;
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
